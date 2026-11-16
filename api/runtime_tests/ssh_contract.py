"""Real runtime user -> generated relay -> WSS -> authorized OpenSSH signing -> disposable server."""

import json
import tempfile
from pathlib import Path

import docker
import docker.errors
from alembic import command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from api.core.config import Config
from api.domains.agents.models import AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.ssh.repository import SshRepository
from api.domains.ssh.runtime import materialize
from api.infrastructure.kubernetes.client import KubernetesClient
from api.runtime_tests.memory_helpers import selected_image
from api.ssh_app import create_ssh_app
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.ssh_runtime import ssh_server, tls_listener
from api.tests.integration.test_ssh import _GIVEN, assign, assignments, create_key, headers, path


def ssh_should_run(runtime: str, tmp_path: Path) -> None:
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
                    repository = context.injector.get(SshRepository)
                    with tls_listener(create_ssh_app(context.injector), tmp_path) as (url, ca):
                        config = context.injector.get(Config)
                        config.ssh_signer_url, config.ssh_ca_certificate = url, ca.read_text()
                        started = context.client.post(
                            assignments(context).removesuffix("ssh-credentials") + "start", headers=headers(context)
                        )
                        assert started.status_code == 200, started.text
                        k8s = context.injector.get(KubernetesClient)
                        token = k8s.create_secret.call_args[0][1].string_data["AGENTBARN_SSH_SIGNER_TOKEN"]
                        deployment = k8s.create_deployment.call_args[0][1]
                        initializer = deployment.spec.template.spec.init_containers[0]
                        keys = repository.runtime_keys(context.agent.id, context.organization.id)
                        artifacts = materialize(keys, enabled=True, url=url, token=token, ca_certificate=ca.read_text())
                        with tempfile.TemporaryDirectory(prefix="ssh-runtime-public-") as directory:
                            public = Path(directory)
                            public.chmod(0o755)
                            for name, content in artifacts.files.items():
                                (public / name).write_text(content)
                                assert "PRIVATE KEY" not in content
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
                                    environment=artifacts.env,
                                    volumes={directory: {"bind": "/app/config", "mode": "ro"}},
                                    tmpfs={"/run/agentbarn-ssh": f"rw,nosuid,nodev,mode=700,uid={uid},gid={gid}"},
                                )

                            try:
                                result = json.loads(run())
                            except docker.errors.ContainerError as exc:
                                raise AssertionError((exc.stderr or b"").decode()) from None
                            assert result["ssh"] and result["git"] and result["scp"] and result["sftp"]
                            assert result["native_terminal"] is True
                            assert result["uid"] == int(uid)
                            assert result["socket_mode"] == "0o600"
                            repository.revoke(context.agent.id)
                            assert json.loads(run(refused=True))["refused"] is True
                            client.close()
