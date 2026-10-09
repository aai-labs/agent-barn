import json
import os
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, is_not

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.models import gateway_token_env_var
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS
from api.domains.integrations.runtime import (
    RuntimeBinding,
    RuntimeContext,
    materialize_integrations,
    select_egress_mode,
)
from api.tests.helpers.integration_credentials import credential_for

_CONTEXT = RuntimeContext(
    home_dir="/opt/data",
    gog_home_dir="/home/hermes",
    store_dir="/opt/data/.config/aai-cli",
    gateway_base_url="http://credential-gateway:8003/gateway/v1",
    gateway_tokens={p: f"gateway-{p.value}" for p in SecretProvider},
)


def _binding(provider: SecretProvider, isolated: bool) -> RuntimeBinding:
    return RuntimeBinding(provider, credential_for(provider), select_egress_mode(provider, isolated=isolated))


@pytest.mark.parametrize("provider", list(SecretProvider))
def test_direct_mode_materializes_provider_credentials_only_in_secret_environment(provider):
    artifacts = materialize_integrations([_binding(provider, False)], _CONTEXT)
    assert_that(json.dumps(artifacts.env), contains_string(f"{provider.value}-provider-secret"))
    assert_that(json.dumps(artifacts.files), is_not(contains_string(f"{provider.value}-provider-secret")))
    assert_that(gateway_token_env_var(provider) in artifacts.env, is_(False))
    assert_that("AF_GATEWAY_URL" in artifacts.env, is_(False))
    if "aai-cli-config.toml" in artifacts.files:
        config = tomllib.loads(artifacts.files["aai-cli-config.toml"])
        assert_that(bool(config["profiles"]), is_(True))
        assert_that(artifacts.files["aai-cli-config.toml"], is_not(contains_string("credential-gateway")))


@pytest.mark.parametrize("provider", list(SecretProvider))
def test_isolated_mode_never_materializes_renewable_credentials(provider):
    artifacts = materialize_integrations([_binding(provider, True)], _CONTEXT)
    serialized = json.dumps({"env": artifacts.env, "files": artifacts.files, "policy": artifacts.policy_md})
    assert_that(serialized, is_not(contains_string(f"{provider.value}-provider-secret")))
    assert_that(serialized, is_not(contains_string("google-client-secret")))
    assert_that(artifacts.env[gateway_token_env_var(provider)], equal_to(f"gateway-{provider.value}"))
    if provider == SecretProvider.GOOGLE_WORKSPACE:
        assert_that("GOG_TOKEN_JSON" in artifacts.env, is_(False))
        assert_that(artifacts.files["gog-shim.sh"], contains_string("GOG_ACCESS_TOKEN"))


def test_mixed_modes_keep_store_injection_separate_from_gateway_profiles():
    bindings = [
        _binding(SecretProvider.GITHUB, False),
        _binding(SecretProvider.JIRA, True),
        _binding(SecretProvider.SHAREPOINT, False),
    ]
    artifacts = materialize_integrations(bindings, _CONTEXT)
    profiles = tomllib.loads(artifacts.files["aai-cli-config.toml"])["profiles"]
    assert_that(profiles["github-work"]["token_secret"], equal_to("github.token"))
    assert_that(profiles["github-work-2"]["repo"], equal_to("two"))
    assert_that(profiles["jira-work"]["token_env"], equal_to(gateway_token_env_var(SecretProvider.JIRA)))
    assert_that(profiles["sharepoint-work"]["auth_type"], equal_to("microsoft_delegated"))
    assert_that("AAI_SECRET_JIRA_API_TOKEN" in artifacts.env, is_(False))
    assert_that(artifacts.files["aai-cli-setup.sh"], contains_string("AAI_SHAREPOINT_SIGN_IN_ID"))
    assert_that(artifacts.files["aai-cli-setup.sh"], is_not(contains_string("secrets set jira.api_token")))


@pytest.mark.parametrize("provider", [SecretProvider.JIRA, SecretProvider.CONFLUENCE])
def test_direct_scoped_atlassian_token_requires_cloud_id(provider):
    original = _binding(provider, False)
    binding = replace(
        original, content=original.content.model_copy(update={"use_scoped_token": True, "cloud_id": None})
    )
    with pytest.raises(ValueError, match="cloud_id"):
        materialize_integrations([binding], _CONTEXT)
    binding = replace(binding, content=binding.content.model_copy(update={"cloud_id": "tenant-cloud-id"}))
    artifacts = materialize_integrations([binding], _CONTEXT)
    assert_that(artifacts.files["aai-cli-config.toml"], contains_string("tenant-cloud-id"))


def test_direct_google_requires_full_client_and_preserves_read_only_guard():
    original = _binding(SecretProvider.GOOGLE_WORKSPACE, False)
    broken = replace(original, content=original.content.model_copy(update={"client_secret": ""}))
    with pytest.raises(ValueError, match="OAuth client"):
        materialize_integrations([broken], _CONTEXT)
    readonly = replace(original, content=original.content.model_copy(update={"read_only": True}))
    artifacts = materialize_integrations([readonly], _CONTEXT)
    assert_that(artifacts.env["GOG_READONLY"], equal_to("1"))
    assert_that(artifacts.env["GOG_ACCOUNT"], equal_to("fixture@example.com"))
    assert_that(json.loads(artifacts.env["GOG_TOKEN_JSON"])["email"], equal_to("fixture@example.com"))
    assert_that("gog-shim.sh" in artifacts.files, is_(False))
    assert_that(artifacts.files["gog-setup.sh"], contains_string("/usr/local/bin/gog auth tokens import"))


def test_google_setup_refuses_to_clear_an_unexpected_state_directory(tmp_path: Path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    artifacts = materialize_integrations([_binding(SecretProvider.GOOGLE_WORKSPACE, False)], _CONTEXT)
    result = subprocess.run(
        ["sh"],
        input=artifacts.files["gog-setup.sh"],
        env={**os.environ, "GOG_HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode, equal_to(78))
    assert_that(sentinel.read_text(), equal_to("keep"))


def test_missing_gateway_authorization_never_falls_back_to_direct():
    with pytest.raises(ValueError, match="Missing gateway authorization"):
        materialize_integrations([_binding(SecretProvider.GITHUB, True)], replace(_CONTEXT, gateway_tokens={}))


@pytest.mark.parametrize("isolated", [False, True])
def test_stored_firecrawl_custom_endpoint_only_applies_to_direct_mode(isolated):
    original = _binding(SecretProvider.FIRECRAWL, isolated)
    binding = replace(original, content=original.content.model_copy(update={"base_url": "https://crawler.example.com"}))
    artifacts = materialize_integrations([binding], _CONTEXT)
    expected = f"{_CONTEXT.gateway_base_url}/p/firecrawl" if isolated else "https://crawler.example.com"
    assert_that(artifacts.env["FIRECRAWL_API_URL"], equal_to(expected))


def test_invalid_provider_route_and_duplicate_bindings_are_rejected():
    assert select_egress_mode(SecretProvider.SHAREPOINT, isolated=True) == EgressMode.TOKEN_BROKER
    github = _binding(SecretProvider.GITHUB, True)
    with pytest.raises(ValueError, match="Unsupported credential route"):
        materialize_integrations([replace(github, mode=EgressMode.TOKEN_BROKER)], _CONTEXT)
    with pytest.raises(ValueError, match="Duplicate binding"):
        materialize_integrations([github, github], _CONTEXT)
    with pytest.raises(TypeError, match="Credential type"):
        materialize_integrations([replace(github, content=credential_for(SecretProvider.JIRA))], _CONTEXT)


def test_adapter_catalogue_covers_every_registered_runtime_tool():
    from api.domains.integrations.runtime import RUNTIME_TOOL_ADAPTERS

    assert_that({p.runtime_tool for p in INTEGRATION_PLUGINS.all()}, equal_to(set(RUNTIME_TOOL_ADAPTERS)))


def test_empty_bindings_retain_persistent_sharepoint_cleanup_without_credentials():
    artifacts = materialize_integrations([], _CONTEXT)
    assert_that(artifacts.env, equal_to({}))
    assert_that(
        artifacts.files["aai-cli-setup.sh"], contains_string("secrets remove microsoft.sharepoint_refresh_token")
    )
    assert_that("aai-cli-config.toml" in artifacts.files, is_(False))
