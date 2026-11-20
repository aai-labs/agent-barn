"""Real runtime user -> generated relay -> WSS -> authorized OpenSSH signing -> disposable server."""

import json
import tempfile
from pathlib import Path
from uuid import UUID

import docker
import docker.errors
from alembic import command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from api.core.config import Config
from api.domains.agents.models import AgentStatus, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.ssh.repository import SshRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.runtime_tests.memory_helpers import selected_image
from api.ssh_app import create_ssh_app
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.ssh_runtime import ssh_server, tls_listener
from api.tests.integration.test_ssh import _GIVEN, assign, create_key, headers, path, ssh_audit_events
from api.tests.steps.agent import there_is_an_agent


def ssh_should_run(runtime: str, tmp_path: Path, *, with_bot: bool = False, shared_key: bool = False) -> None:
    image = selected_image(runtime)
    root = Path(__file__).resolve().parents[2]
    with PostgresContainer("postgres:18", driver="psycopg2") as postgres:  # noqa: SIM117
        with given(
            [
                set_env_variable(
                    {
                        "DB_CONNECTION_URL": postgres.get_connection_url(),
                        "SECRET_SIGNING_KEY": "ssh-runtime-test-key-32-characters",
                        "PLATFORM_ADMIN_CREDENTIALS": "admin@example.com:Test1234",
                        "ENVIRONMENT": "test",
                        "ANALYTICS_ENABLED": "false",
                        "CLOUDFLARE_API_TOKEN": "",
                        "AGENTBARN_TELEGRAM_BOT_TOKEN": "",
                        "ORGANIZATION_DEFAULT_LLM_BUDGET_USD": "100",
                        "AGENT_DEFAULT_LLM_BUDGET_USD": "25",
                    }
                )
            ]
        ):
            command.upgrade(AlembicConfig(str(root / "api/alembic.ini")), "head")
            with given(_GIVEN) as context:
                context.agent.agent_type = AgentType(runtime)
                context.injector.get(AgentRepository).save(context.agent)
                parent = context.agent
                if with_bot:
                    there_is_an_agent(
                        name="SSH Bot",
                        status=AgentStatus.STOPPED,
                        agent_type=AgentType(runtime),
                        parent_agent_id=parent.id,
                        bot_slot=1,
                    )(context)
                setattr(context.injector.get(Config), f"{runtime}_image", image)
                created = create_key(context).json()
                with ssh_server(tmp_path / "server", created["public_key"]) as (port, host_public):
                    update = {
                        "expected_revision": 1,
                        "name": created["name"],
                        "enabled": True,
                        "mode": "restricted",
                        "servers": [
                            {
                                "name": "fixture",
                                "hostname": "127.0.0.1",
                                "port": port,
                                "username": "root",
                                "host_keys": [host_public],
                            }
                        ],
                    }
                    assert (
                        context.client.put(
                            path(context, "/" + created["id"]), headers=headers(context), json=update
                        ).status_code
                        == 200
                    )
                    assert assign(context, [created["id"]]).status_code == 200
                    if shared_key:
                        parent_assignments = (
                            f"/api/v1/organizations/{parent.organization_id}/agents/{parent.id}/ssh-credentials"
                        )
                        assert (
                            context.client.put(
                                parent_assignments,
                                headers=headers(context),
                                json={"credential_ids": [created["id"]], "expected_revision": 0},
                            ).status_code
                            == 200
                        )
                    repository = context.injector.get(SshRepository)
                    with tls_listener(create_ssh_app(context.injector), tmp_path) as (url, ca):
                        config = context.injector.get(Config)
                        config.ssh_signer_url, config.ssh_ca_certificate = url, ca.read_text()
                        started = context.client.post(
                            f"/api/v1/organizations/{parent.organization_id}/agents/{parent.id}/start",
                            headers=headers(context),
                        )
                        assert started.status_code == 200, started.text
                        k8s = context.injector.get(KubernetesClient)
                        secrets = {
                            call.args[1].metadata.name: call.args[1].string_data
                            for call in k8s.create_secret.call_args_list
                        }
                        configs = {
                            call.args[1].metadata.name: call.args[1].data
                            for call in k8s.create_config_map.call_args_list
                        }
                        deployment = k8s.create_deployment.call_args[0][1]
                        initializer = deployment.spec.template.spec.init_containers[0]
                        key = repository.key(UUID(created["id"]), context.organization.id)
                        assert key is not None
                        private = decrypt_token(key.private_key_encrypted, config.agent_token_encryption_key)
                        with tempfile.TemporaryDirectory(prefix="ssh-runtime-public-") as directory:
                            public = Path(directory)
                            public.chmod(0o755)
                            for name, content in configs[f"agent-{parent.id}"].items():
                                (public / name).write_text(content)
                                assert private not in content
                            volumes = {directory: {"bind": "/app/config", "mode": "ro"}}
                            if with_bot:
                                for label, values, target in (
                                    (
                                        "bot-config",
                                        configs[f"agent-{context.agent.id}"],
                                        f"/app/bots/{context.agent.id}",
                                    ),
                                    (
                                        "bot-secret",
                                        secrets[f"agent-{context.agent.id}"],
                                        f"/run/agentbarn/bots/{context.agent.id}",
                                    ),
                                ):
                                    mounted = public / label
                                    mounted.mkdir(mode=0o755)
                                    for name, value in values.items():
                                        (mounted / name).write_text(value)
                                        assert private not in value
                                    volumes[str(mounted)] = {"bind": target, "mode": "ro"}
                            driver = Path(__file__).parent / "fixtures/ssh_driver.py"
                            (public / "driver.py").write_text(driver.read_text())
                            client = docker.from_env()
                            identity = client.containers.run(
                                image, ["-c", "id -u; id -g"], entrypoint="sh", remove=True
                            )
                            uid, gid = identity.decode().strip().splitlines()[-2:]
                            # Execute the exact generated Kubernetes init argv in
                            # the selected image. A direct chown argv must not
                            # accidentally receive shell syntax as its path.
                            data, socket_root = tmp_path / "data", tmp_path / "relay"
                            data.mkdir()
                            socket_root.mkdir()
                            data_root = "/opt/data" if runtime == "hermes" else "/home/node/.openclaw"
                            client.containers.run(
                                image,
                                initializer.command[1:],
                                entrypoint=initializer.command[0],
                                user="0:0",
                                remove=True,
                                volumes={
                                    str(data): {"bind": data_root, "mode": "rw"},
                                    str(socket_root): {"bind": "/run/agentbarn-ssh", "mode": "rw"},
                                },
                            )
                            assert socket_root.stat().st_uid == int(uid)
                            assert socket_root.stat().st_gid == int(gid)
                            assert socket_root.stat().st_mode & 0o777 == 0o700

                            def run(refused: bool = False) -> bytes:
                                return client.containers.run(
                                    image,
                                    ["/app/config/driver.py", runtime, *(["--expect-refusal"] if refused else [])],
                                    entrypoint="python3",
                                    working_dir="/tmp",
                                    network_mode="host",
                                    remove=True,
                                    environment={
                                        **secrets[f"agent-{parent.id}"],
                                        **({"SSH_TEST_BOT_ID": str(context.agent.id)} if with_bot else {}),
                                    },
                                    volumes=volumes,
                                    tmpfs={
                                        name: f"rw,nosuid,nodev,mode=700,uid={uid},gid={gid}"
                                        for name in ("/run/agentbarn-ssh", "/run/agentbarn/env", "/workspace")
                                    },
                                )

                            try:
                                result = json.loads(run())
                            except docker.errors.ContainerError as exc:
                                raise AssertionError((exc.stderr or b"").decode()) from None
                            assert result["ssh"] and result["git"] and result["scp"] and result["sftp"]
                            assert result["native_terminal"] is True
                            assert result["bot"] is with_bot
                            assert result["uid"] == int(uid)
                            assert result["socket_mode"] == "0o600"
                            issued = [
                                event for event in ssh_audit_events(context) if event.event_name == "ssh.signing.issued"
                            ]
                            assert issued
                            assert all(event.payload["agent_id"] == str(context.agent.id) for event in issued)
                            repository.revoke(context.agent.id)
                            assert json.loads(run(refused=True))["refused"] is True
                            client.close()
