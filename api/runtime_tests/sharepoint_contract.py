"""Real-image SharePoint direct/isolated handoff and CLI compatibility contract."""

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.aai_store import sharepoint_refresh_token
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS
from api.domains.integrations.runtime import RuntimeBinding, RuntimeContext, materialize_integrations
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.integration_credentials import credential_for


def _prepare(runtime: str, root: Path):
    def step(context):
        context.image = os.environ.get(f"{runtime.upper()}_TEST_IMAGE")
        if not context.image:
            pytest.fail(f"{runtime.upper()}_TEST_IMAGE must name a built runtime image")
        home = "/opt/data" if runtime == "hermes" else "/home/node"
        store = f"{home}/.config/aai-cli" if runtime == "hermes" else "/home/node/.openclaw/aai-cli"
        selected = RuntimeContext(
            home_dir=home,
            gog_home_dir=home,
            store_dir=store,
            gateway_base_url="http://127.0.0.1:18080/gateway/v1",
            gateway_tokens={provider: f"agt_{provider.value}_fixture" for provider in SecretProvider},
        )
        content = credential_for(SecretProvider.SHAREPOINT)
        payload = {"home": home, "store": store}
        for name, mode, grant in (
            ("direct", EgressMode.DIRECT, content),
            ("isolated", EgressMode.TOKEN_BROKER, content),
            (
                "handback",
                EgressMode.DIRECT,
                content.model_copy(
                    update={"refresh_token": "latest-service-grant", "store_revision": "service-revision"}
                ),
            ),
        ):
            bindings = [RuntimeBinding(SecretProvider.SHAREPOINT, grant, mode)]
            for plugin in INTEGRATION_PLUGINS.for_tool("aai-cli"):
                if plugin.provider != SecretProvider.SHAREPOINT:
                    route = (
                        EgressMode.DIRECT
                        if name == "direct" or plugin.provider == SecretProvider.GITHUB
                        else plugin.egress_mode
                    )
                    bindings.append(RuntimeBinding(plugin.provider, credential_for(plugin.provider), route))
            payload[name] = asdict(materialize_integrations(bindings, selected))
        (root / "artifacts.json").write_text(json.dumps(payload))
        (root / "artifacts.json").chmod(0o644)
        (root / "config").mkdir()
        (root / "config").chmod(0o777)
        root.chmod(0o755)
        context.root = root

    return step


def sharepoint_should_handoff(runtime: str, root: Path) -> None:
    with given([_prepare(runtime, root)]) as context:
        with when("the generated setup and pinned CLI run as the image user with external networking disabled"):
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--mount",
                    f"type=bind,src={root},dst=/contract,readonly",
                    "--mount",
                    f"type=bind,src={root / 'config'},dst=/app/config",
                    "--mount",
                    f"type=bind,src={Path(__file__).parent / 'fixtures/sharepoint_driver.py'},dst=/driver.py,readonly",
                    "--entrypoint",
                    "python3",
                    context.image,
                    "/driver.py",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            observed = json.loads(result.stdout)
        with then(
            "failed import preserves the rotated PVC grant and successful import uses only the dedicated gateway token"
        ):
            assert observed["uid"] != 0
            assert (
                sharepoint_refresh_token(store_json=observed["prior"]["store"], key_text=observed["prior"]["key"])
                == "rotated-pvc-grant"
            )
            assert (
                sharepoint_refresh_token(observed["final"]["store"], observed["final"]["key"]) == "latest-service-grant"
            )
            imports = [r for r in observed["requests"] if r["path"].endswith("/handoff")]
            assert (
                sharepoint_refresh_token(imports[0]["body"]["store"], imports[0]["body"]["key"]) == "rotated-pvc-grant"
            )
            assert all(r["authorization"] == "Bearer agt_sharepoint_fixture" for r in observed["requests"])
            assert len([r for r in observed["requests"] if r["path"].endswith("/token")]) >= 4
