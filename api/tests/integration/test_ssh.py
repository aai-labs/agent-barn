import base64
import os
import struct
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat
from fastapi.testclient import TestClient
from hamcrest import assert_that, equal_to
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.events.models import OutboxMessage
from api.domains.integrations.repository import IntegrationRepository
from api.domains.ssh.protocol import string
from api.domains.ssh.repository import SshRepository, token_digest
from api.domains.ssh.signer import OpenSshSigner
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.ssh_app import SUBPROTOCOL, create_ssh_app
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "SSH_ENABLED": "true",
            "SSH_SIGNER_URL": "wss://signer.example/ssh/v1/agent",
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.STOPPED),
]


def headers(context):
    return {"Authorization": "Bearer " + context.access_token}


def path(context, suffix=""):
    return f"/api/v1/organizations/{context.organization.id}/ssh-credentials{suffix}"


def assignments(context):
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/ssh-credentials"


def create_key(context, **overrides):
    return context.client.post(
        path(context), headers=headers(context), json={"name": "Deployment key", "source": "generate", **overrides}
    )


def assign(context, keys, revision=0, **extra):
    return context.client.put(
        assignments(context),
        headers=headers(context),
        json={"credential_ids": keys, "expected_revision": revision, **extra},
    )


def public_blob(key):
    return base64.b64decode(key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).split()[1])


def bind(host, session):
    signature = string(b"ssh-ed25519") + string(host.sign(session))
    return (
        b"\x1b"
        + string(b"session-bind@openssh.com")
        + string(public_blob(host))
        + string(session)
        + string(signature)
        + b"\x00"
    )


def sign_request(public, session, user=b"deploy"):
    data = string(session) + b"\x32" + string(user) + string(b"ssh-connection") + string(b"publickey")
    data += b"\x01" + string(b"ssh-ed25519") + string(public)
    return b"\x0d" + string(public) + string(data) + struct.pack(">I", 0)


def activate(context, keys):
    repository = context.injector.get(SshRepository)
    runtime = context.injector.get(IntegrationRepository)
    generation = runtime.begin(context.agent.id, {})
    runtime.set_state(context.agent.id, "provisioned")
    context.agent.status = AgentStatus.RUNNING
    context.injector.get(AgentRepository).save(context.agent)
    rows = repository.runtime_keys(context.agent.id, context.organization.id)
    return repository.issue(context.agent.id, context.organization.id, generation.generation, rows)


def test_generate_multiple_assignments_never_exports_keys_and_restricts_deletion():
    with given(_GIVEN) as context:
        with when("two keys are generated and assigned"):
            first, second = create_key(context), create_key(context, name="Other key")
            assert first.status_code == second.status_code == 201
            ids = [first.json()["id"], second.json()["id"]]
            response = assign(context, ids)
        with then("public metadata is readable and assignments are independent"):
            assert_that(response.status_code, equal_to(200))
            assert len(response.json()["credentials"]) == 2
            assert response.json()["revision"] == 1
            assert response.json()["allowed_actions"] == ["manage"]
            assert "PRIVATE KEY" not in response.text
            assert context.client.delete(path(context, "/" + ids[0]), headers=headers(context)).status_code == 409
        with when("a stale edit and cross-organization reference are submitted"):
            assert assign(context, [], revision=0).status_code == 409
            assert assign(context, [str(uuid4())], revision=1).status_code == 404
            foreign = path(context, "/" + ids[0]).replace(str(context.organization.id), str(uuid4()))
            assert context.client.get(foreign, headers=headers(context)).status_code in (403, 404)
        with then("detaching permits deletion and events contain no key material"):
            assert assign(context, [], revision=1).status_code == 200
            assert context.client.delete(path(context, "/" + ids[0]), headers=headers(context)).status_code == 204
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                events = list(
                    session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name).like("ssh.%"))).all()
                )
                assert len(events) >= 5
                assert "PRIVATE KEY" not in str([e.payload for e in events])


def test_import_encrypted_key_duplicate_key_and_safe_validation():
    with given(_GIVEN) as context:
        private = Ed25519PrivateKey.generate()
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption

        pem = private.private_bytes(
            Encoding.PEM, PrivateFormat.OpenSSH, BestAvailableEncryption(b"private-passphrase")
        ).decode()
        first = create_key(context, source="import", private_key=pem, passphrase="private-passphrase")
        assert first.status_code == 201
        assert "private-passphrase" not in first.text and "PRIVATE KEY" not in first.text
        assert (
            create_key(
                context, source="import", name="duplicate", private_key=pem, passphrase="private-passphrase"
            ).status_code
            == 409
        )
        for data in [
            {"private_key": pem, "passphrase": "wrong"},
            {"private_key": "sensitive-bogus-input"},
            {"private_key": pem, "source": "generate"},
        ]:
            response = (
                create_key(context, source="import", **{k: v for k, v in data.items() if k != "source"})
                if "source" not in data
                else create_key(context, **data)
            )
            assert response.status_code == 422
            assert "PRIVATE KEY" not in response.text and "sensitive-bogus-input" not in response.text
        row = context.injector.get(SshRepository).key(UUID(first.json()["id"]), context.organization.id)
        assert "PRIVATE KEY" not in row.private_key_encrypted


def test_policy_cas_and_malicious_profile_fields_are_rejected():
    with given(_GIVEN) as context:
        row = create_key(context).json()
        updated = {"name": row["name"], "enabled": False, "mode": "unrestricted", "expected_revision": 1}
        assert (
            context.client.put(path(context, "/" + row["id"]), headers=headers(context), json=updated).status_code
            == 200
        )
        assert (
            context.client.put(path(context, "/" + row["id"]), headers=headers(context), json=updated).status_code
            == 409
        )
        for name in ["host\nProxyCommand evil", "-option", "bad name"]:
            response = create_key(
                context,
                servers=[{"name": "host", "hostname": name, "username": "deploy", "host_keys": [row["public_key"]]}],
            )
            assert response.status_code == 422


def test_generation_revocation_and_readding_do_not_restore_old_authority():
    with given(_GIVEN) as context:
        key = create_key(context, mode="unrestricted").json()
        assert assign(context, [key["id"]]).status_code == 200
        token = activate(context, [key])
        repository = context.injector.get(SshRepository)
        assert len(repository.authorize(token_digest(token))[1]) == 1
        assert assign(context, [], revision=1).status_code == 200
        assert repository.authorize(token_digest(token))[1] == []
        # Re-adding to a live Agent requires explicit restart; it cannot revive the old snapshot.
        assert assign(context, [key["id"]], revision=2).status_code == 409
        repository.revoke(context.agent.id)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            repository.authorize(token_digest(token))


def test_real_signer_restricts_host_account_and_all_keyring_mutations(tmp_path):
    with given(_GIVEN) as context:
        host = Ed25519PrivateKey.generate()
        host_public = host.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
        created = create_key(
            context,
            servers=[{"name": "prod", "hostname": "prod.example", "username": "deploy", "host_keys": [host_public]}],
        ).json()
        assert assign(context, [created["id"]]).status_code == 200
        token = activate(context, [created])
        public = base64.b64decode(created["public_key"].split()[1])
        session = os.urandom(32)
        client = TestClient(create_ssh_app(context.injector))
        with client.websocket_connect(
            "/ssh/v1/agent", subprotocols=[SUBPROTOCOL], headers={"Authorization": "Bearer " + token}
        ) as ws:
            ws.send_bytes(b"\x0b")
            assert ws.receive_bytes()[0] == 12
            ws.send_bytes(sign_request(public, session))
            assert ws.receive_bytes() == b"\x05"
            ws.send_bytes(bind(host, session))
            assert ws.receive_bytes() == b"\x06"
            ws.send_bytes(sign_request(public, session))
            assert ws.receive_bytes()[0] == 14
            ws.send_bytes(sign_request(public, session, b"root"))
            assert ws.receive_bytes() == b"\x05"
            for operation in [9, 17, 18, 19, 20, 21, 22, 23, 25, 26]:
                ws.send_bytes(bytes([operation]))
                assert ws.receive_bytes() == b"\x05"
            ws.send_bytes(sign_request(public, session))
            assert ws.receive_bytes()[0] == 14
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as database:
            outcomes = database.exec(
                select(OutboxMessage.event_name).where(col(OutboxMessage.event_name).like("ssh.signing.%"))
            ).all()
            assert outcomes.count("ssh.signing.issued") == 2
            assert outcomes.count("ssh.signing.refused") == 2


def test_empty_restricted_policy_never_loads_unrestricted_key(tmp_path):
    with given(_GIVEN) as context:
        created = create_key(context).json()
        key = context.injector.get(SshRepository).key(UUID(created["id"]), context.organization.id)
        with OpenSshSigner([key], TEST_ENCRYPTION_KEY, str(tmp_path)) as signer:
            response = signer.exchange(b"\x0b")
            assert response == b"\x0c\x00\x00\x00\x00"


def test_unauthenticated_access_is_rejected():
    with given(_GIVEN) as context:
        assert context.client.get(path(context)).status_code == 401
        assert context.client.get(assignments(context)).status_code == 401


def test_normal_ssh_git_scp_sftp_through_real_tls_relay(tmp_path):
    import importlib.util
    import json
    import subprocess
    import sys
    import time

    from api.domains.ssh.runtime import materialize
    from api.tests.helpers.ssh_runtime import ssh_server, tls_listener

    with given(_GIVEN) as context:
        created = create_key(context, mode="unrestricted").json()
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
            token = activate(context, [created])
            repository = context.injector.get(SshRepository)
            keys = repository.runtime_keys(context.agent.id, context.organization.id)
            with tls_listener(create_ssh_app(context.injector), tmp_path) as (url, ca):
                artifacts = materialize(keys, enabled=True, url=url, token=token)
                assert "PRIVATE KEY" not in str(artifacts)
                relay = tmp_path / "ssh-agent-relay.py"
                relay.write_text(artifacts.files["ssh-agent-relay.py"])
                manifest = tmp_path / "profiles.json"
                manifest.write_text(artifacts.files["ssh-client.json"])
                spec = importlib.util.spec_from_file_location("ssh_relay_fixture", relay)
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                root = tmp_path / "relay"
                module.configure(root, str(manifest), tmp_path / "home/config")
                env = {
                    **os.environ,
                    **artifacts.env,
                    "SSH_AUTH_SOCK": str(root / "agent.sock"),
                    "AGENTBARN_SSH_DIRECTORY": str(root),
                    "AGENTBARN_SSH_CA_FILE": str(ca),
                }
                process = subprocess.Popen(
                    [sys.executable, str(relay)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
                try:
                    deadline = time.monotonic() + 10
                    while not (root / "agent.sock").exists():
                        assert process.poll() is None, "Relay must start"
                        assert time.monotonic() < deadline
                        time.sleep(0.02)
                    alias = json.loads(manifest.read_text())[0]["alias"]
                    config = str(root / "config")

                    def run(command, *, check=True, **kwargs):
                        result = subprocess.run(
                            command, env=env, capture_output=True, timeout=30, check=False, **kwargs
                        )
                        if check:
                            assert result.returncode == 0, result.stderr.decode()
                        return result

                    for _ in range(12):
                        result = run(["ssh", "-vvv", "-F", config, alias, "printf ssh-connected"])
                        assert result.stdout == b"ssh-connected"
                    run(["ssh", "-F", config, alias, "git init --bare /tmp/fixture.git >/dev/null"])
                    git_env = {**env, "GIT_SSH_COMMAND": f"ssh -vvv -F {config}"}
                    clone = subprocess.run(
                        ["git", "clone", f"{alias}:/tmp/fixture.git", str(tmp_path / "clone")],
                        env=git_env,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    assert clone.returncode == 0, clone.stderr.decode()
                    content = tmp_path / "report.txt"
                    content.write_text("transferred without a private key")
                    run(["scp", "-F", config, str(content), f"{alias}:/tmp/report.txt"])
                    received = tmp_path / "download.txt"
                    run(["sftp", "-F", config, "-b", "-", alias], input=f"get /tmp/report.txt {received}\n".encode())
                    assert received.read_text() == content.read_text()
                    # Client-side host checking and signer-side policy are independent.
                    (root / "known_hosts").write_text("")
                    refused = run(["ssh", "-F", config, alias, "true"], check=False)
                    assert refused.returncode != 0
                    assert b"Host key verification failed" in refused.stderr
                    repository.revoke(context.agent.id)
                    refused = run(["ssh", "-F", config, "-o", "StrictHostKeyChecking=no", alias, "true"], check=False)
                    assert refused.returncode != 0
                finally:
                    process.terminate()
                    process.wait(timeout=5)
                    assert process.stderr is not None
                    stderr = process.stderr.read().decode()
                    if stderr:
                        print("Relay diagnostics:", stderr)


@pytest.mark.parametrize(
    "role_name,read_status,write_status",
    [("owner", 200, 200), ("editor", 200, 200), ("viewer", 200, 403), ("unassigned", 404, 404)],
)
def test_members_need_agent_credential_authority_and_cannot_manage_shared_keys(role_name, read_status, write_status):
    from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
    from api.domains.users.organization_users.models import OrganizationRole
    from api.tests.steps.agent import there_is_agent_access
    from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

    with given(_GIVEN) as context:
        key = create_key(context).json()
        steps = [
            there_is_a_user(
                email=f"{role_name}@example.com", role=OrganizationRole.MEMBER, organization_id=context.organization.id
            ),
            there_is_an_access_token_for_user(),
        ]
        for step in steps:
            step(context)
        with when("the member uses the SSH credential surfaces"):
            if role_name != "unassigned":
                there_is_agent_access(
                    access_role_id={
                        "owner": AGENT_OWNER_ROLE_ID,
                        "editor": AGENT_EDITOR_ROLE_ID,
                        "viewer": AGENT_VIEWER_ROLE_ID,
                    }[role_name]
                )(context)
            assert context.client.get(path(context), headers=headers(context)).status_code == 200
            assert create_key(context, name="Member-created key").status_code == 403
            assert context.client.get(assignments(context), headers=headers(context)).status_code == read_status
            response = assign(context, [key["id"]])
            assert response.status_code == write_status


def test_wrong_host_and_forged_bindings_fail_and_changed_policy_closes_live_socket():
    from starlette.websockets import WebSocketDisconnect

    with given(_GIVEN) as context:
        allowed = Ed25519PrivateKey.generate()
        public = allowed.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
        created = create_key(
            context,
            servers=[{"name": "allowed", "hostname": "allowed.example", "username": "deploy", "host_keys": [public]}],
        ).json()
        assert assign(context, [created["id"]]).status_code == 200
        token = activate(context, [created])
        client = TestClient(create_ssh_app(context.injector))
        with client.websocket_connect(
            "/ssh/v1/agent", subprotocols=[SUBPROTOCOL], headers={"Authorization": "Bearer " + token}
        ) as ws:
            wrong = Ed25519PrivateKey.generate()
            session = os.urandom(32)
            ws.send_bytes(bind(wrong, session))
            assert ws.receive_bytes() == b"\x06"
            ws.send_bytes(sign_request(base64.b64decode(created["public_key"].split()[1]), session))
            assert ws.receive_bytes() == b"\x05"
        with client.websocket_connect(
            "/ssh/v1/agent", subprotocols=[SUBPROTOCOL], headers={"Authorization": "Bearer " + token}
        ) as ws:
            forged = bytearray(bind(allowed, os.urandom(32)))
            forged[-2] ^= 0xFF
            ws.send_bytes(bytes(forged))
            assert ws.receive_bytes() == b"\x05"
            update = {"name": created["name"], "enabled": False, "mode": "restricted", "expected_revision": 1}
            assert (
                context.client.put(
                    path(context, "/" + created["id"]), headers=headers(context), json=update
                ).status_code
                == 200
            )
            ws.send_bytes(b"\x0b")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_bytes()


@pytest.mark.parametrize("failed_outcome", ["authorized", "issued"])
def test_failed_audit_does_not_release_signature(monkeypatch, failed_outcome):
    from starlette.websockets import WebSocketDisconnect

    with given(_GIVEN) as context:
        key = create_key(context, mode="unrestricted").json()
        assert assign(context, [key["id"]]).status_code == 200
        token = activate(context, [key])
        repository = context.injector.get(SshRepository)
        original = repository.record_signing

        def fail_outcome(state, key, outcome, request_id, host_fingerprint=None):
            if outcome == failed_outcome:
                raise RuntimeError("audit store unavailable")
            original(state, key, outcome, request_id, host_fingerprint)

        monkeypatch.setattr(repository, "record_signing", fail_outcome)
        with TestClient(create_ssh_app(context.injector)).websocket_connect(
            "/ssh/v1/agent", subprotocols=[SUBPROTOCOL], headers={"Authorization": "Bearer " + token}
        ) as ws:
            ws.send_bytes(sign_request(base64.b64decode(key["public_key"].split()[1]), os.urandom(32)))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_bytes()


def test_protocol_rejects_forwarding_malformed_frames_and_excess_connections():
    from starlette.websockets import WebSocketDisconnect

    from api.core.config import Config

    with given(_GIVEN) as context:
        key = create_key(context, mode="unrestricted").json()
        assert assign(context, [key["id"]]).status_code == 200
        token = activate(context, [key])
        context.injector.get(Config).ssh_max_agent_connections = 1
        client = TestClient(create_ssh_app(context.injector))
        connection = {"subprotocols": [SUBPROTOCOL], "headers": {"Authorization": "Bearer " + token}}
        with client.websocket_connect("/ssh/v1/agent", **connection) as ws:
            with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ssh/v1/agent", **connection):
                pass
            for payload in [b"", b"\x0d", b"\x0bextra", b"\x1b" + string(b"unknown"), b"x" * (256 * 1024 + 1)]:
                ws.send_bytes(payload)
                assert ws.receive_bytes() == b"\x05"
            forwarded = bind(Ed25519PrivateKey.generate(), os.urandom(32))[:-1] + b"\x01"
            ws.send_bytes(forwarded)
            assert ws.receive_bytes() == b"\x05"
            ws.send_bytes(b"\x0b")
            assert ws.receive_bytes()[0] == 12
            metrics = client.get("/metrics").text
            assert "agentbarn_ssh_connections 1.0" in metrics
            assert token not in metrics and key["id"] not in metrics
            context.injector.get(SshRepository).revoke(context.agent.id)
            ws.send_bytes(b"\x0bextra")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_bytes()


def test_downgrade_preserves_keys_until_explicitly_removed():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig

    with given(_GIVEN) as context:
        key = create_key(context).json()
        migration = AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with pytest.raises(RuntimeError, match="Detach and delete SSH credentials"):
            command.downgrade(migration, "-1")
        assert context.client.get(path(context, "/" + key["id"]), headers=headers(context)).status_code == 200
        assert context.client.delete(path(context, "/" + key["id"]), headers=headers(context)).status_code == 204
        try:
            command.downgrade(migration, "-1")
        finally:
            command.upgrade(migration, "head")


def test_tenant_foreign_keys_and_stale_generations_are_enforced():
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from api.domains.ssh.models import AgentSshCredential

    with given(_GIVEN) as context:
        key = create_key(context, mode="unrestricted").json()
        assert assign(context, [key["id"]]).status_code == 200
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with pytest.raises(IntegrityError):
            delegate.save(
                AgentSshCredential(agent_id=context.agent.id, credential_id=UUID(key["id"]), organization_id=uuid4())
            )
        token = activate(context, [key])
        context.injector.get(IntegrationRepository).begin(context.agent.id, {})
        with pytest.raises(HTTPException):
            context.injector.get(SshRepository).authorize(token_digest(token))


def test_agent_start_materializes_only_public_ssh_files_and_generation_token():
    from api.infrastructure.crypto import decrypt_token
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        key = create_key(context, mode="unrestricted").json()
        stored = context.injector.get(SshRepository).key(UUID(key["id"]), context.organization.id)
        assert stored is not None
        private_body = decrypt_token(stored.private_key_encrypted, TEST_ENCRYPTION_KEY).splitlines()[1]
        assert assign(context, [key["id"]]).status_code == 200
        response = context.client.post(
            assignments(context).removesuffix("ssh-credentials") + "start", headers=headers(context)
        )
        assert response.status_code == 200, response.text
        k8s = context.injector.get(KubernetesClient)
        secret = k8s.create_secret.call_args[0][1]
        assert secret.string_data["SSH_AUTH_SOCK"] == "/run/agentbarn-ssh/agent.sock"
        assert secret.string_data["AGENTBARN_SSH_SIGNER_URL"].startswith("wss://")
        assert secret.string_data["AGENTBARN_SSH_SIGNER_TOKEN"].startswith("abssh_")
        assert private_body not in str(secret.string_data)
        assert stored.private_key_encrypted not in str(secret.string_data)
        config = k8s.create_config_map.call_args[0][1]
        assert "ssh-agent-relay.py" in config.data
        assert private_body not in str(config.data)
        assert stored.private_key_encrypted not in str(config.data)
        token = secret.string_data["AGENTBARN_SSH_SIGNER_TOKEN"]
        assert len(context.injector.get(SshRepository).authorize(token_digest(token))[1]) == 1
