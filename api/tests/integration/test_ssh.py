import base64
import os
import struct
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat
from fastapi.testclient import TestClient
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_items, has_key, has_length, is_in, not_
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.events.models import OutboxMessage
from api.domains.integrations.repository import IntegrationRepository
from api.domains.ssh.protocol import string
from api.domains.ssh.repository import SshRepository, token_digest
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


def there_are_shared_ssh_keys(*names, **overrides):
    def step(context):
        context.ssh_keys = []
        for name in names or ("Deployment key",):
            response = create_key(context, name=name, **overrides)
            assert_that(response.status_code, equal_to(201))
            context.ssh_keys.append(response.json())

    return step


def the_ssh_keys_are_assigned():
    def step(context):
        response = assign(context, [key["id"] for key in context.ssh_keys])
        assert_that(response.status_code, equal_to(200))

    return step


def the_ssh_keys_have_been_detached():
    def step(context):
        response = assign(context, [], revision=1)
        assert_that(response.status_code, equal_to(200))

    return step


def there_is_an_encrypted_import(*, already_saved=False):
    def step(context):
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption

        private = Ed25519PrivateKey.generate()
        context.import_payload = {
            "source": "import",
            "private_key": private.private_bytes(
                Encoding.PEM, PrivateFormat.OpenSSH, BestAvailableEncryption(b"private-passphrase")
            ).decode(),
            "passphrase": "private-passphrase",
        }
        if already_saved:
            response = create_key(context, **context.import_payload)
            assert_that(response.status_code, equal_to(201))

    return step


def the_ssh_key_policy_has_changed():
    def step(context):
        key = context.ssh_keys[0]
        context.policy_update = {"name": key["name"], "enabled": False, "mode": "unrestricted", "expected_revision": 1}
        response = context.client.put(
            path(context, "/" + key["id"]), headers=headers(context), json=context.policy_update
        )
        assert_that(response.status_code, equal_to(200))

    return step


def ssh_audit_events(context):
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name).like("ssh.%"))).all())


def test_an_administrator_can_generate_a_key_without_exporting_private_material():
    with given(_GIVEN) as context:
        with when("the administrator generates a shared SSH key"):
            response = create_key(context)

        with then("only the public identity is returned"):
            assert_that(response.status_code, equal_to(201))
            assert_that(response.json(), has_entries(name="Deployment key", mode="restricted", revision=1))
            assert_that(response.json()["public_key"], contains_string("ssh-ed25519"))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))
            assert_that(response.json(), not_(has_key("private_key")))
            assert_that(response.json(), not_(has_key("private_key_encrypted")))


def test_an_agent_can_be_assigned_multiple_shared_keys():
    with given([*_GIVEN, there_are_shared_ssh_keys("Deployment key", "Other key")]) as context:
        ids = [key["id"] for key in context.ssh_keys]
        with when("both shared keys are assigned to the Agent"):
            response = assign(context, ids)

        with then("the saved selection contains both public identities"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json()["credentials"], has_length(2))
            assert_that(response.json(), has_entries(revision=1, allowed_actions=["manage"]))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that({key["id"] for key in saved["credentials"]}, equal_to(set(ids)))

        with then("the durable audit records contain no private material"):
            events = ssh_audit_events(context)
            assert_that([event.event_name for event in events], has_items("ssh.key.created", "ssh.assignments.changed"))
            assert_that(str([event.payload for event in events]), not_(contains_string("PRIVATE KEY")))


def test_an_assigned_key_cannot_be_deleted():
    with given([*_GIVEN, there_are_shared_ssh_keys(), the_ssh_keys_are_assigned()]) as context:
        key = context.ssh_keys[0]
        with when("the administrator deletes an attached key"):
            response = context.client.delete(path(context, "/" + key["id"]), headers=headers(context))

        with then("deletion is refused and the public identity remains available"):
            assert_that(response.status_code, equal_to(409))
            saved = context.client.get(path(context, "/" + key["id"]), headers=headers(context))
            assert_that(saved.status_code, equal_to(200))
            assert_that(saved.json()["public_key"], equal_to(key["public_key"]))


@pytest.mark.parametrize("requested_keys,revision,status", [("empty", 0, 409), ("missing", 1, 404)])
def test_a_rejected_assignment_preserves_the_agents_existing_keys(requested_keys, revision, status):
    with given([*_GIVEN, there_are_shared_ssh_keys(), the_ssh_keys_are_assigned()]) as context:
        requested = [] if requested_keys == "empty" else [str(uuid4())]
        with when("a stale revision or missing shared key is submitted"):
            response = assign(context, requested, revision=revision)

        with then("the request is refused without changing the selection"):
            assert_that(response.status_code, equal_to(status))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that([key["id"] for key in saved["credentials"]], equal_to([context.ssh_keys[0]["id"]]))
            assert_that(saved["revision"], equal_to(1))


def test_a_key_cannot_be_read_through_another_organizations_url():
    with given([*_GIVEN, there_are_shared_ssh_keys()]) as context:
        foreign = path(context, "/" + context.ssh_keys[0]["id"]).replace(str(context.organization.id), str(uuid4()))
        with when("the key is requested through an inaccessible Organization"):
            response = context.client.get(foreign, headers=headers(context))

        with then("the key is concealed"):
            assert_that(response.status_code, is_in((403, 404)))
            assert_that(response.text, not_(contains_string(context.ssh_keys[0]["public_key"])))


def test_a_detached_key_can_be_deleted():
    with given(
        [*_GIVEN, there_are_shared_ssh_keys(), the_ssh_keys_are_assigned(), the_ssh_keys_have_been_detached()]
    ) as context:
        url = path(context, "/" + context.ssh_keys[0]["id"])
        with when("the administrator deletes the detached key"):
            response = context.client.delete(url, headers=headers(context))

        with then("the key is removed"):
            assert_that(response.status_code, equal_to(204))
            assert_that(context.client.get(url, headers=headers(context)).status_code, equal_to(404))

        with then("the removal is recorded without private material"):
            events = ssh_audit_events(context)
            assert_that([event.event_name for event in events], has_items("ssh.key.deleted"))
            assert_that(str([event.payload for event in events]), not_(contains_string("PRIVATE KEY")))


def test_an_encrypted_key_can_be_imported_without_exposing_its_private_material():
    with given([*_GIVEN, there_is_an_encrypted_import()]) as context:
        with when("the administrator imports the key with its passphrase"):
            response = create_key(context, **context.import_payload)

        with then("only public metadata is returned and the stored key is encrypted"):
            assert_that(response.status_code, equal_to(201))
            assert_that(response.text, not_(contains_string("private-passphrase")))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))
            stored = context.injector.get(SshRepository).key(UUID(response.json()["id"]), context.organization.id)
            assert_that(stored, not_(equal_to(None)))
            assert_that(stored.private_key_encrypted, not_(contains_string("PRIVATE KEY")))


def test_the_same_public_key_cannot_be_imported_under_another_name():
    with given([*_GIVEN, there_is_an_encrypted_import(already_saved=True)]) as context:
        with when("the administrator imports the existing key under a different name"):
            response = create_key(context, name="Duplicate identity", **context.import_payload)

        with then("the duplicate identity is refused"):
            assert_that(response.status_code, equal_to(409))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))


@pytest.mark.parametrize("invalid_input", ["wrong-passphrase", "malformed-key", "generated-with-private-input"])
def test_invalid_imports_are_refused_without_echoing_secret_fields(invalid_input):
    with given([*_GIVEN, there_is_an_encrypted_import()]) as context:
        payload = dict(context.import_payload)
        if invalid_input == "wrong-passphrase":
            payload["passphrase"] = "wrong"
        elif invalid_input == "malformed-key":
            payload = {"source": "import", "private_key": "sensitive-bogus-input"}
        else:
            payload["source"] = "generate"
        with when("the invalid private material is submitted"):
            response = create_key(context, **payload)

        with then("validation refuses the input without echoing it"):
            assert_that(response.status_code, equal_to(422))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))
            assert_that(response.text, not_(contains_string("sensitive-bogus-input")))
            assert_that(response.text, not_(contains_string("private-passphrase")))


def test_a_stale_policy_update_preserves_the_saved_policy():
    with given([*_GIVEN, there_are_shared_ssh_keys(), the_ssh_key_policy_has_changed()]) as context:
        url = path(context, "/" + context.ssh_keys[0]["id"])
        with when("the old policy revision is submitted again"):
            response = context.client.put(url, headers=headers(context), json=context.policy_update)

        with then("the edit is refused and the saved policy remains at the new revision"):
            assert_that(response.status_code, equal_to(409))
            saved = context.client.get(url, headers=headers(context)).json()
            assert_that(saved, has_entries(enabled=False, mode="unrestricted", revision=2))


@pytest.mark.parametrize("hostname", ["host\nProxyCommand evil", "-option", "bad name"])
def test_ssh_configuration_injection_is_refused(hostname):
    with given([*_GIVEN, there_are_shared_ssh_keys()]) as context:
        server = {
            "name": "host",
            "hostname": hostname,
            "username": "deploy",
            "host_keys": [context.ssh_keys[0]["public_key"]],
        }
        with when("an unsafe server address is submitted"):
            response = create_key(context, name="Unsafe destination", servers=[server])

        with then("no unsafe SSH profile is accepted"):
            assert_that(response.status_code, equal_to(422))


def there_is_an_active_signing_key(*, restricted=True, empty=False):
    def step(context):
        context.host = Ed25519PrivateKey.generate()
        context.session_id = os.urandom(32)
        host_public = context.host.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
        policy = {"mode": "unrestricted"} if not restricted else {}
        if restricted and not empty:
            policy["servers"] = [
                {"name": "prod", "hostname": "prod.example", "username": "deploy", "host_keys": [host_public]}
            ]
        there_are_shared_ssh_keys(**policy)(context)
        the_ssh_keys_are_assigned()(context)
        context.key = context.ssh_keys[0]
        context.public = base64.b64decode(context.key["public_key"].split()[1])
        context.token = activate(context, [context.key])

    return step


def there_is_a_signing_connection(*, bound=False, wrong_host=False, limit=8):
    from contextlib import contextmanager

    @contextmanager
    def step(context):
        from api.core.config import Config

        context.injector.get(Config).ssh_max_agent_connections = limit
        context.signing_client = TestClient(create_ssh_app(context.injector))
        context.connection = {"subprotocols": [SUBPROTOCOL], "headers": {"Authorization": "Bearer " + context.token}}
        with context.signing_client.websocket_connect("/ssh/v1/agent", **context.connection) as socket:
            context.socket = socket
            if bound:
                host = Ed25519PrivateKey.generate() if wrong_host else context.host
                assert_that(exchange(context, bind(host, context.session_id)), equal_to(b"\x06"))
            yield

    return step


def exchange(context, payload):
    context.socket.send_bytes(payload)
    return context.socket.receive_bytes()


def request_signature(context, user=b"deploy"):
    return exchange(context, sign_request(context.public, context.session_id, user))


def the_signing_credential_is_revoked():
    def step(context):
        context.injector.get(SshRepository).revoke(context.agent.id)

    return step


def authorize_signing_credential(context):
    return context.injector.get(SshRepository).authorize(token_digest(context.token))


def test_detaching_a_key_immediately_removes_its_applied_grant():
    with given([*_GIVEN, there_is_an_active_signing_key(restricted=False)]) as context:
        with when("the running Agent's key is detached"):
            response = assign(context, [], revision=1)
        with then("the old token no longer grants the key"):
            assert_that(response.status_code, equal_to(200))
            assert_that(authorize_signing_credential(context)[1], has_length(0))


def test_readding_a_detached_key_does_not_restore_old_authority():
    with given(
        [*_GIVEN, there_is_an_active_signing_key(restricted=False), the_ssh_keys_have_been_detached()]
    ) as context:
        with when("the key is re-added without Apply & Restart"):
            response = assign(context, [context.key["id"]], revision=2)
        with then("the addition is refused and the old token remains without a grant"):
            assert_that(response.status_code, equal_to(409))
            assert_that(authorize_signing_credential(context)[1], has_length(0))


def test_revoked_signing_credentials_are_refused():
    from fastapi import HTTPException

    with given(
        [*_GIVEN, there_is_an_active_signing_key(restricted=False), the_signing_credential_is_revoked()]
    ) as context:
        with when("the old signing credential is authorized"):
            with pytest.raises(HTTPException) as refused:
                authorize_signing_credential(context)
        with then("the runtime has no signing authority"):
            assert_that(refused.value.status_code, equal_to(403))


@pytest.mark.parametrize(
    "bound,wrong_host,user,expected",
    [(False, False, b"deploy", 5), (True, False, b"deploy", 14), (True, False, b"root", 5), (True, True, b"deploy", 5)],
    ids=["unbound", "allowed", "wrong-account", "wrong-host"],
)
def test_restricted_signing_requires_a_verified_host_and_allowed_account(bound, wrong_host, user, expected):
    with given(
        [*_GIVEN, there_is_an_active_signing_key(), there_is_a_signing_connection(bound=bound, wrong_host=wrong_host)]
    ) as context:
        with when("the client requests an authentication signature"):
            response = request_signature(context, user)
        with then("OpenSSH enforces host and account constraints"):
            assert_that(response[0], equal_to(expected))
        with then("both authorization and the signing result are durably recorded"):
            outcomes = [event.event_name for event in ssh_audit_events(context)]
            assert_that(outcomes.count("ssh.signing.authorized"), equal_to(1))
            assert_that(outcomes.count("ssh.signing.issued" if expected == 14 else "ssh.signing.refused"), equal_to(1))


@pytest.mark.parametrize("operation", [9, 17, 18, 19, 20, 21, 22, 23, 25, 26])
def test_keyring_mutations_are_refused_without_removing_the_allowed_key(operation):
    with given([*_GIVEN, there_is_an_active_signing_key(), there_is_a_signing_connection(bound=True)]) as context:
        with when("the client attempts to mutate the signer's keyring"):
            response = exchange(context, bytes([operation]))
        with then("the operation is refused and the original key still signs"):
            assert_that(response, equal_to(b"\x05"))
            assert_that(request_signature(context)[0], equal_to(14))


def test_empty_restricted_policy_never_loads_an_unrestricted_key():
    with given([*_GIVEN, there_is_an_active_signing_key(empty=True), there_is_a_signing_connection()]) as context:
        with when("the client requests available identities"):
            response = exchange(context, b"\x0b")
        with then("the empty restricted policy exposes no signing identity"):
            assert_that(response, equal_to(b"\x0c\x00\x00\x00\x00"))


@pytest.mark.parametrize("surface", ["shared-keys", "agent-assignments"])
def test_ssh_credentials_cannot_be_read_without_authentication(surface):
    with given(_GIVEN) as context:
        url = path(context) if surface == "shared-keys" else assignments(context)
        with when("the SSH resource is requested without authentication"):
            response = context.client.get(url)

        with then("the caller must authenticate"):
            assert_that(response.status_code, equal_to(401))


def there_is_a_real_ssh_destination(root):
    from contextlib import contextmanager

    from api.domains.ssh.runtime import materialize
    from api.tests.helpers.ssh_runtime import relay_client, ssh_server, tls_listener

    @contextmanager
    def step(context):
        there_are_shared_ssh_keys(mode="unrestricted")(context)
        key = context.ssh_keys[0]
        with ssh_server(root / "server", key["public_key"]) as (port, host_public):
            update = {
                "expected_revision": 1,
                "name": key["name"],
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
            response = context.client.put(path(context, "/" + key["id"]), headers=headers(context), json=update)
            assert_that(response.status_code, equal_to(200))
            the_ssh_keys_are_assigned()(context)
            token = activate(context, [key])
            keys = context.injector.get(SshRepository).runtime_keys(context.agent.id, context.organization.id)
            with tls_listener(create_ssh_app(context.injector), root) as (url, ca):
                context.artifacts = materialize(keys, enabled=True, url=url, token=token)
                with relay_client(context.artifacts, ca, root) as relay:
                    context.relay = relay
                    yield

    return step


def run_ordinary_ssh_tools(context, root):
    import subprocess

    relay = context.relay
    ssh = ["ssh", "-F", relay.config, relay.alias]
    connections = [relay.run([*ssh, "printf ssh-connected"]) for _ in range(12)]
    initialized = relay.run([*ssh, "git init --bare /tmp/fixture.git >/dev/null"])
    clone = subprocess.run(
        ["git", "clone", f"{relay.alias}:/tmp/fixture.git", str(root / "clone")],
        env=relay.git_env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    content = root / "report.txt"
    content.write_text("transferred without a private key")
    sent = relay.run(["scp", "-F", relay.config, str(content), f"{relay.alias}:/tmp/report.txt"])
    received = root / "download.txt"
    downloaded = relay.run(
        ["sftp", "-F", relay.config, "-b", "-", relay.alias], input=f"get /tmp/report.txt {received}\n".encode()
    )
    return connections, [initialized, clone, sent, downloaded], received


def test_normal_ssh_git_scp_sftp_through_real_tls_relay(tmp_path):
    with given([*_GIVEN, there_is_a_real_ssh_destination(tmp_path)]) as context:
        with when("ordinary SSH, Git and file-transfer tools use the real TLS relay"):
            connections, transfers, received = run_ordinary_ssh_tools(context, tmp_path)
        with then("repeated independent SSH sessions and all file-transfer operations succeed"):
            for result in [*connections, *transfers]:
                assert_that(result.returncode, equal_to(0), result.stderr.decode())
            assert_that([result.stdout for result in connections], equal_to([b"ssh-connected"] * 12))
            assert_that(received.read_text(), equal_to("transferred without a private key"))
        with then("the Agent receives no private key"):
            assert_that(str(context.artifacts), not_(contains_string("PRIVATE KEY")))


def the_client_does_not_trust_the_server():
    def step(context):
        (context.relay.directory / "known_hosts").write_text("")

    return step


def test_ordinary_ssh_refuses_an_untrusted_server(tmp_path):
    with given([*_GIVEN, there_is_a_real_ssh_destination(tmp_path), the_client_does_not_trust_the_server()]) as context:
        with when("ordinary SSH connects without a trusted server key"):
            result = context.relay.run(["ssh", "-F", context.relay.config, context.relay.alias, "true"])
        with then("client host verification refuses the connection"):
            assert_that(result.returncode, not_(equal_to(0)))
            assert_that(result.stderr.decode(), contains_string("Host key verification failed"))


def test_ordinary_ssh_refuses_revoked_credentials_even_when_client_trust_is_bypassed(tmp_path):
    with given(
        [
            *_GIVEN,
            there_is_a_real_ssh_destination(tmp_path),
            the_client_does_not_trust_the_server(),
            the_signing_credential_is_revoked(),
        ]
    ) as context:
        with when("the client bypasses local host checks after its signing token is revoked"):
            result = context.relay.run(
                ["ssh", "-F", context.relay.config, "-o", "StrictHostKeyChecking=no", context.relay.alias, "true"]
            )
        with then("signer-side revocation still prevents authentication"):
            assert_that(result.returncode, not_(equal_to(0)))


def there_is_an_organization_member_with_agent_access(role_name):
    def step(context):
        from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
        from api.domains.users.organization_users.models import OrganizationRole
        from api.tests.steps.agent import there_is_agent_access
        from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

        there_is_a_user(
            email=f"{role_name}@example.com", role=OrganizationRole.MEMBER, organization_id=context.organization.id
        )(context)
        there_is_an_access_token_for_user()(context)
        if role_name != "unassigned":
            there_is_agent_access(
                access_role_id={
                    "owner": AGENT_OWNER_ROLE_ID,
                    "editor": AGENT_EDITOR_ROLE_ID,
                    "viewer": AGENT_VIEWER_ROLE_ID,
                }[role_name]
            )(context)

    return step


def request_ssh_surface(context, surface):
    if surface == "shared-key-list":
        return context.client.get(path(context), headers=headers(context))
    if surface == "shared-key-create":
        return create_key(context, name="Member-created key")
    if surface == "agent-read":
        return context.client.get(assignments(context), headers=headers(context))
    return assign(context, [context.ssh_keys[0]["id"]])


@pytest.mark.parametrize("surface", ["shared-key-list", "shared-key-create", "agent-read", "agent-write"])
@pytest.mark.parametrize(
    "role_name,read_status,write_status",
    [("owner", 200, 200), ("editor", 200, 200), ("viewer", 200, 403), ("unassigned", 404, 404)],
)
def test_ssh_access_respects_organization_and_agent_authority(role_name, read_status, write_status, surface):
    with given(
        [*_GIVEN, there_are_shared_ssh_keys(), there_is_an_organization_member_with_agent_access(role_name)]
    ) as context:
        expected = {
            "shared-key-list": 200,
            "shared-key-create": 403,
            "agent-read": read_status,
            "agent-write": write_status,
        }
        with when("the member requests the SSH credential operation"):
            response = request_ssh_surface(context, surface)

        with then("Organization membership and Agent authority determine access"):
            assert_that(response.status_code, equal_to(expected[surface]))
            assert_that(response.text, not_(contains_string("PRIVATE KEY")))


def forged_binding(context):
    payload = bytearray(bind(context.host, context.session_id))
    payload[-2] ^= 0xFF
    return bytes(payload)


def test_forged_session_binding_is_refused():
    with given([*_GIVEN, there_is_an_active_signing_key(), there_is_a_signing_connection()]) as context:
        with when("the client submits a forged host signature"):
            response = exchange(context, forged_binding(context))
        with then("OpenSSH rejects the session binding"):
            assert_that(response, equal_to(b"\x05"))


def the_active_key_policy_is_disabled():
    def step(context):
        update = {"name": context.key["name"], "enabled": False, "mode": "restricted", "expected_revision": 1}
        response = context.client.put(path(context, "/" + context.key["id"]), headers=headers(context), json=update)
        assert_that(response.status_code, equal_to(200))

    return step


def test_changed_policy_closes_the_existing_signing_connection():
    from starlette.websockets import WebSocketDisconnect

    with given(
        [
            *_GIVEN,
            there_is_an_active_signing_key(),
            there_is_a_signing_connection(),
            the_active_key_policy_is_disabled(),
        ]
    ) as context:
        with when("the existing connection requests identities after a policy change"):
            with pytest.raises(WebSocketDisconnect) as refused:
                exchange(context, b"\x0b")
        with then("the connection with the obsolete policy is closed"):
            assert_that(refused.value.code, equal_to(1008))


def audit_persistence_fails(monkeypatch, failed_outcome):
    def step(context):
        repository = context.injector.get(SshRepository)
        original = repository.record_signing

        def fail_outcome(state, key, outcome, request_id, host_fingerprint=None):
            if outcome == failed_outcome:
                raise RuntimeError("audit store unavailable")
            original(state, key, outcome, request_id, host_fingerprint)

        monkeypatch.setattr(repository, "record_signing", fail_outcome)

    return step


@pytest.mark.parametrize("failed_outcome", ["authorized", "issued"])
def test_failed_audit_does_not_release_signature(monkeypatch, failed_outcome):
    from starlette.websockets import WebSocketDisconnect

    with given(
        [
            *_GIVEN,
            there_is_an_active_signing_key(restricted=False),
            audit_persistence_fails(monkeypatch, failed_outcome),
            there_is_a_signing_connection(),
        ]
    ) as context:
        with when("a signature is requested while audit persistence fails"):
            with pytest.raises(WebSocketDisconnect) as refused:
                request_signature(context)
        with then("the client receives no signature and the connection closes"):
            assert_that(refused.value.code, equal_to(1011))
            outcomes = [event.event_name for event in ssh_audit_events(context)]
            assert_that(outcomes.count("ssh.signing.issued"), equal_to(0))
            assert_that(outcomes.count("ssh.signing.authorized"), equal_to(0 if failed_outcome == "authorized" else 1))


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x0d", b"\x0bextra", b"\x1b" + string(b"unknown"), b"x" * (256 * 1024 + 1)],
    ids=["empty", "incomplete-signature", "trailing-data", "unknown-extension", "oversize"],
)
def test_malformed_agent_frames_are_refused_without_closing_the_connection(payload):
    with given([*_GIVEN, there_is_an_active_signing_key(restricted=False), there_is_a_signing_connection()]) as context:
        with when("the client sends a malformed or unsupported frame"):
            response = exchange(context, payload)
        with then("the frame is refused and the connection remains usable"):
            assert_that(response, equal_to(b"\x05"))
            assert_that(exchange(context, b"\x0b")[0], equal_to(12))


def test_forwarded_session_binding_is_refused():
    with given([*_GIVEN, there_is_an_active_signing_key(restricted=False), there_is_a_signing_connection()]) as context:
        payload = bind(context.host, context.session_id)[:-1] + b"\x01"
        with when("the client requests a forwarded session binding"):
            response = exchange(context, payload)
        with then("the forwarded binding is refused"):
            assert_that(response, equal_to(b"\x05"))


def test_excess_connections_are_refused_without_disrupting_the_existing_connection():
    from starlette.websockets import WebSocketDisconnect

    with given(
        [*_GIVEN, there_is_an_active_signing_key(restricted=False), there_is_a_signing_connection(limit=1)]
    ) as context:
        with when("a second connection exceeds the Agent's connection limit"):
            with pytest.raises(WebSocketDisconnect) as refused:
                with context.signing_client.websocket_connect("/ssh/v1/agent", **context.connection):
                    pass
        with then("the excess connection is refused and the existing client still works"):
            assert_that(refused.value.code, equal_to(1013))
            assert_that(exchange(context, b"\x0b")[0], equal_to(12))


def test_metrics_expose_connection_count_without_runtime_identity():
    with given([*_GIVEN, there_is_an_active_signing_key(restricted=False), there_is_a_signing_connection()]) as context:
        with when("the internal metrics endpoint is inspected"):
            metrics = context.signing_client.get("/metrics").text
        with then("counts are visible without signing credentials or key IDs"):
            assert_that(metrics, contains_string("agentbarn_ssh_connections 1.0"))
            assert_that(metrics, not_(contains_string(context.token)))
            assert_that(metrics, not_(contains_string(context.key["id"])))


def test_revocation_closes_existing_connections_even_for_malformed_requests():
    from starlette.websockets import WebSocketDisconnect

    with given(
        [
            *_GIVEN,
            there_is_an_active_signing_key(restricted=False),
            there_is_a_signing_connection(),
            the_signing_credential_is_revoked(),
        ]
    ) as context:
        with when("a revoked client sends a malformed request"):
            with pytest.raises(WebSocketDisconnect) as refused:
                exchange(context, b"\x0bextra")
        with then("revocation takes precedence over frame rejection"):
            assert_that(refused.value.code, equal_to(1008))


def downgrade_ssh_schema():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig

    migration = AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.downgrade(migration, "-1")


def test_downgrade_preserves_keys_until_explicitly_removed():
    with given([*_GIVEN, there_are_shared_ssh_keys()]) as context:
        with when("schema rollback is attempted while a shared key exists"):
            with pytest.raises(RuntimeError) as refused:
                downgrade_ssh_schema()
        with then("the migration refuses rollback without deleting the key"):
            assert_that(str(refused.value), contains_string("Detach and delete SSH credentials"))
            saved = context.client.get(path(context, "/" + context.ssh_keys[0]["id"]), headers=headers(context))
            assert_that(saved.status_code, equal_to(200))


def the_ssh_key_has_been_deleted():
    def step(context):
        response = context.client.delete(path(context, "/" + context.ssh_keys[0]["id"]), headers=headers(context))
        assert_that(response.status_code, equal_to(204))

    return step


def test_downgrade_succeeds_after_keys_are_explicitly_removed():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import inspect

    with given([*_GIVEN, there_are_shared_ssh_keys(), the_ssh_key_has_been_deleted()]) as context:
        try:
            with when("schema rollback is requested without stored keys"):
                downgrade_ssh_schema()
            with then("the SSH tables are removed"):
                tables = inspect(context.injector.get(PostgresRepositoryDelegate).engine).get_table_names()
                assert_that(tables, not_(has_items("ssh_credential")))
        finally:
            command.upgrade(AlembicConfig(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")


def organization_cascades_visit(first_table):
    def step(context):
        from sqlalchemy import text

        engine = context.injector.get(PostgresRepositoryDelegate).engine
        quote = engine.dialect.identifier_preparer.quote
        order = (first_table, "agent" if first_table == "ssh_credential" else "ssh_credential")
        # Recreating equivalent FKs represents a valid restore/rebuild ordering.
        # Exercise both sibling cascade orders instead of relying on migration OIDs.
        with engine.begin() as connection:
            for table in order:
                name, definition = connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = to_regclass(:table) AND confrelid = 'organization'::regclass AND contype = 'f'"
                    ),
                    {"table": table},
                ).one()
                connection.execute(text(f"ALTER TABLE {quote(table)} DROP CONSTRAINT {quote(name)}"))
                connection.execute(text(f"ALTER TABLE {quote(table)} ADD CONSTRAINT {quote(name)} {definition}"))
            ordered = (
                connection.execute(
                    text(
                        "SELECT c.conrelid::regclass::text FROM pg_trigger t "
                        "JOIN pg_constraint c ON c.oid = t.tgconstraint JOIN pg_proc p ON p.oid = t.tgfoid "
                        "WHERE t.tgrelid = 'organization'::regclass AND p.proname = 'RI_FKey_cascade_del' "
                        "AND c.conrelid IN ('agent'::regclass, 'ssh_credential'::regclass) ORDER BY t.tgname"
                    )
                )
                .scalars()
                .all()
            )
        assert_that(ordered[0], equal_to(first_table))

    return step


@pytest.mark.parametrize("first_table", ["ssh_credential", "agent"])
def test_organization_hard_delete_cleans_up_assigned_ssh_keys_in_either_cascade_order(first_table):
    from api.domains.agents.models import Agent
    from api.domains.organizations.models import Organization
    from api.domains.organizations.repository import OrganizationRepository
    from api.domains.ssh.models import AgentSshCredential, SshCredential, SshRuntimeCredential

    with given(
        [*_GIVEN, there_are_shared_ssh_keys(), the_ssh_keys_are_assigned(), organization_cascades_visit(first_table)]
    ) as context:
        key_id = UUID(context.ssh_keys[0]["id"])
        with when("the Organization is hard-deleted at the persistence boundary"):
            removed = context.injector.get(OrganizationRepository).delete(context.organization.id)

        with then("the Organization, Agent and all SSH ownership rows are removed together"):
            assert_that(removed, equal_to(True))
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                assert_that(session.get(Organization, context.organization.id), equal_to(None))
                assert_that(session.get(Agent, context.agent.id), equal_to(None))
                assert_that(session.get(SshCredential, key_id), equal_to(None))
                assert_that(
                    session.exec(
                        select(AgentSshCredential).where(AgentSshCredential.agent_id == context.agent.id)
                    ).all(),
                    has_length(0),
                )
                assert_that(
                    session.exec(
                        select(SshRuntimeCredential).where(SshRuntimeCredential.agent_id == context.agent.id)
                    ).all(),
                    has_length(0),
                )


def test_the_database_still_refuses_direct_deletion_of_an_assigned_ssh_key():
    from sqlalchemy.exc import IntegrityError

    from api.domains.ssh.models import SshCredential

    with given([*_GIVEN, there_are_shared_ssh_keys(), the_ssh_keys_are_assigned()]) as context:
        key_id = UUID(context.ssh_keys[0]["id"])
        with when("an assigned key is deleted directly in the database"):
            with (
                pytest.raises(IntegrityError) as refused,
                Session(context.injector.get(PostgresRepositoryDelegate).engine) as session,
            ):
                session.delete(session.get(SshCredential, key_id))
                session.commit()

        with then("the foreign key refuses deletion and the selection is preserved"):
            assert_that(str(getattr(refused.value.orig, "pgcode", None)), is_in(("23001", "23503")))
            saved = context.client.get(assignments(context), headers=headers(context)).json()
            assert_that([key["id"] for key in saved["credentials"]], equal_to([str(key_id)]))


def test_tenant_foreign_keys_refuse_cross_organization_assignments():
    from sqlalchemy.exc import IntegrityError

    from api.domains.ssh.models import AgentSshCredential

    with given([*_GIVEN, there_are_shared_ssh_keys()]) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with when("an assignment is persisted with the wrong Organization"):
            with pytest.raises(IntegrityError) as refused:
                delegate.save(
                    AgentSshCredential(
                        agent_id=context.agent.id,
                        credential_id=UUID(context.ssh_keys[0]["id"]),
                        organization_id=uuid4(),
                    )
                )
        with then("a tenant foreign key rejects the assignment"):
            assert_that(getattr(refused.value.orig, "pgcode", None), equal_to("23503"))


def a_new_runtime_generation_has_replaced_the_signing_generation():
    def step(context):
        context.injector.get(IntegrationRepository).begin(context.agent.id, {})

    return step


def test_stale_generations_cannot_authorize_signing():
    from fastapi import HTTPException

    with given(
        [
            *_GIVEN,
            there_is_an_active_signing_key(restricted=False),
            a_new_runtime_generation_has_replaced_the_signing_generation(),
        ]
    ) as context:
        with when("the previous generation's signing credential is presented"):
            with pytest.raises(HTTPException) as refused:
                authorize_signing_credential(context)
        with then("the obsolete generation has no signing authority"):
            assert_that(refused.value.status_code, equal_to(403))


def start_the_agent(context):
    return context.client.post(assignments(context).removesuffix("ssh-credentials") + "start", headers=headers(context))


def test_agent_start_materializes_only_public_ssh_files_and_generation_token():
    from api.infrastructure.crypto import decrypt_token
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given([*_GIVEN, there_are_shared_ssh_keys(mode="unrestricted"), the_ssh_keys_are_assigned()]) as context:
        stored = context.injector.get(SshRepository).key(UUID(context.ssh_keys[0]["id"]), context.organization.id)
        private_body = decrypt_token(stored.private_key_encrypted, TEST_ENCRYPTION_KEY).splitlines()[1]
        with when("the Agent starts with a shared SSH key"):
            response = start_the_agent(context)
        with then("its generated Secret has a generation token and local socket, with no private material"):
            assert_that(response.status_code, equal_to(200), response.text)
            k8s = context.injector.get(KubernetesClient)
            secret = k8s.create_secret.call_args[0][1]
            assert_that(secret.string_data["SSH_AUTH_SOCK"], equal_to("/run/agentbarn-ssh/agent.sock"))
            assert_that(secret.string_data["AGENTBARN_SSH_SIGNER_URL"], contains_string("wss://"))
            assert_that(secret.string_data["AGENTBARN_SSH_SIGNER_TOKEN"], contains_string("abssh_"))
            assert_that(str(secret.string_data), not_(contains_string(private_body)))
            assert_that(str(secret.string_data), not_(contains_string(stored.private_key_encrypted)))
        with then("its ConfigMap contains only public relay files and its signing token resolves the key"):
            config = k8s.create_config_map.call_args[0][1]
            assert_that(config.data, has_key("ssh-agent-relay.py"))
            assert_that(str(config.data), not_(contains_string(private_body)))
            assert_that(str(config.data), not_(contains_string(stored.private_key_encrypted)))
            keys = context.injector.get(SshRepository).authorize(
                token_digest(secret.string_data["AGENTBARN_SSH_SIGNER_TOKEN"])
            )[1]
            assert_that(keys, has_length(1))
