import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_length, is_not, none
from sqlmodel import Session, select

from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
)
from api.domains.conversations.models import AgentChatMessage
from api.domains.events.catalog import AGENT_UPDATED
from api.domains.events.models import OutboxMessage
from api.domains.personas.models import AgentPersona, AgentPersonaVersion
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given
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

BASE = "/api/v1/organizations/{organization_id}/agents"


def _given(*, flag: str = "true", agent_type: AgentType = AgentType.HERMES, soul_md: str = "# Soul\n\nTest soul."):
    return [
        set_env_variable({"PERSONAS_ENABLED": flag, "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(name="Ada", agent_type=agent_type, soul_md=soul_md),
    ]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(context, suffix: str = "") -> str:
    return f"{BASE}/{context.agent.id}/personas{suffix}"


def _seed(context, key="sales", versions=1, deleted=False) -> AgentPersona:
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        persona = AgentPersona(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            key=key,
            display_name=key.title(),
            emoji="💼",
            current_version=versions,
            deleted_at=datetime.now(UTC) if deleted else None,
        )
        session.add(persona)
        session.flush()
        for number in range(1, versions + 1):
            session.add(
                AgentPersonaVersion(
                    organization_id=context.organization.id,
                    persona_id=persona.id,
                    version=number,
                    soul_md=f"{key} soul v{number}",
                    identity_md=f"{key} identity v{number}",
                    author_user_id=context.user.id,
                )
            )
        session.commit()
    return persona


def test_the_list_starts_with_the_default_then_active_personas_without_bodies():
    with given(_given()) as context:
        _seed(context, "sales")
        _seed(context, "lawyer")
        _seed(context, "gone", deleted=True)

        response = context.client.get(_url(context), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["enabled"], equal_to(True))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default", "sales", "lawyer"]))
        default, sales = body["personas"][0], body["personas"][1]
        assert_that(default["id"], none())
        assert_that(default["is_default"], equal_to(True))
        assert_that(default["display_name"], equal_to("Ada"))
        assert_that(default["current_version"], none())
        assert_that(sales["is_default"], equal_to(False))
        assert_that(sales["emoji"], equal_to("💼"))
        assert_that(sales["current_version"], equal_to(1))
        assert_that("soul_md" in sales, equal_to(False))


def test_the_list_reports_disabled_when_the_flag_is_off_but_still_shows_existing_rows():
    with given(_given(flag="false")) as context:
        _seed(context, "sales")

        body = context.client.get(_url(context), headers=_auth(context)).json()

        assert_that(body["enabled"], equal_to(False))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default", "sales"]))


def test_an_openclaw_agent_only_has_the_default_and_is_never_enabled():
    with given(_given(agent_type=AgentType.OPENCLAW)) as context:
        _seed(context, "sales")

        body = context.client.get(_url(context), headers=_auth(context)).json()

        assert_that(body["enabled"], equal_to(False))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default"]))
        response = context.client.get(_url(context, "/sales"), headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_reading_a_persona_returns_its_current_version():
    with given(_given()) as context:
        _seed(context, "sales", versions=2)

        response = context.client.get(_url(context, "/sales"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["current_version"], equal_to(2))
        assert_that(body["soul_md"], equal_to("sales soul v2"))
        assert_that(body["identity_md"], equal_to("sales identity v2"))


def test_reading_the_default_renders_the_template_placeholders():
    with given(_given(soul_md="You are {{agent_display_name}}.")) as context:
        response = context.client.get(_url(context, "/default"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["is_default"], equal_to(True))
        assert_that(body["id"], none())
        assert_that(body["soul_md"], equal_to("You are Ada."))
        assert_that(body["identity_md"], is_not(none()))


@pytest.mark.parametrize("key", ["nosuch", "gone"])
def test_an_unknown_or_deleted_persona_is_not_found(key):
    with given(_given()) as context:
        _seed(context, "gone", deleted=True)

        for suffix in (f"/{key}", f"/{key}/versions"):
            response = context.client.get(_url(context, suffix), headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_versions_are_listed_newest_first():
    with given(_given()) as context:
        _seed(context, "sales", versions=3)

        response = context.client.get(_url(context, "/sales/versions"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that([item["version"] for item in body], equal_to([3, 2, 1]))
        assert_that(body[0]["soul_md"], equal_to("sales soul v3"))
        assert_that(body[0]["author_user_id"], equal_to(str(context.user.id)))


def test_the_default_has_no_versions():
    with given(_given()) as context:
        response = context.client.get(_url(context, "/default/versions"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_length(0))


def _body(name="Sales", **fields) -> dict:
    return {"display_name": name, "emoji": "💼", "soul_md": "Soul", "identity_md": "Identity", **fields}


def _create(context, name="Sales", **fields):
    return context.client.post(_url(context), json=_body(name, **fields), headers=_auth(context))


def _set_agent(context, **fields) -> None:
    with Session(context.postgres_delegate.engine) as session:
        agent = session.get(Agent, context.agent.id)
        assert agent is not None
        for field, value in fields.items():
            setattr(agent, field, value)
        session.add(agent)
        session.commit()


def _persona_events(context) -> list[OutboxMessage]:
    with Session(context.postgres_delegate.engine) as session:
        messages = session.exec(select(OutboxMessage)).all()
    return [message for message in messages if message.event_name == AGENT_UPDATED]


def test_creating_a_persona_stores_it_with_version_one():
    with given(_given()) as context:
        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(body["key"], equal_to("sales"))
        assert_that(body["display_name"], equal_to("Sales"))
        assert_that(body["emoji"], equal_to("💼"))
        assert_that(body["current_version"], equal_to(1))
        assert_that(body["soul_md"], equal_to("Soul"))
        versions = context.client.get(_url(context, "/sales/versions"), headers=_auth(context)).json()
        assert_that(versions, has_length(1))
        assert_that(versions[0]["author_user_id"], equal_to(str(context.user.id)))


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Sales Team EU", "sales-team-eu"),
        ("  Ünï Bot!  ", "n-bot"),
        ("x" * 60, "x" * 40),
        ("default", "persona-1"),
        ("Hermes", "persona-1"),
        ("root", "persona-1"),
        ("venv", "persona-1"),
        ("node_modules", "node-modules"),
        ("CON", "persona-1"),
        ("com1", "persona-1"),
        ("日本語", "persona-1"),
    ],
)
def test_keys_are_derived_from_the_name(name, key):
    with given(_given()) as context:
        response = _create(context, name)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.json()["key"], equal_to(key))


def test_a_client_cannot_choose_the_key():
    with given(_given()) as context:
        response = _create(context, key="chosen")

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_a_name_collision_gets_a_numbered_key_even_after_deletion():
    with given(_given()) as context:
        _seed(context, "sales", deleted=True)

        first = _create(context)
        second = _create(context)

        assert_that(first.json()["key"], equal_to("sales-2"))
        assert_that(second.json()["key"], equal_to("sales-3"))


def test_a_long_name_collision_stays_within_the_key_limit():
    with given(_given()) as context:
        first = _create(context, "x" * 60)
        second = _create(context, "x" * 60)

        assert_that(first.json()["key"], equal_to("x" * 40))
        assert_that(second.json()["key"], equal_to("x" * 38 + "-2"))


def test_creating_is_refused_when_the_flag_is_off():
    with given(_given(flag="false")) as context:
        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_creating_on_openclaw_is_refused_with_400():
    with given(_given(agent_type=AgentType.OPENCLAW)) as context:
        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_creating_while_running_is_refused():
    with given(_given()) as context:
        _set_agent(context, status=AgentStatus.RUNNING)

        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_creating_during_a_managed_update_is_refused():
    with given(_given()) as context:
        _set_agent(context, managed_update_heartbeat_at=datetime.now(UTC))

        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_sixth_active_persona_is_refused_and_deleted_ones_do_not_count():
    with given(_given()) as context:
        _seed(context, "gone", deleted=True)
        for name in ("one", "two", "three", "four", "five"):
            assert_that(_create(context, name).status_code, equal_to(status.HTTP_201_CREATED))

        response = _create(context, "six")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


@pytest.mark.parametrize("field", ["soul_md", "identity_md"])
def test_text_is_capped_at_32_kib_in_bytes(field):
    with given(_given()) as context:
        assert_that(_create(context, "fits", **{field: "x" * 32768}).status_code, equal_to(status.HTTP_201_CREATED))

        too_long = _create(context, "long", **{field: "x" * 32769})
        too_many_bytes = _create(context, "bytes", **{field: "ą" * 16385})

        assert_that(too_long.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
        assert_that(too_many_bytes.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_the_name_is_trimmed_but_prompt_text_is_kept_exactly():
    with given(_given()) as context:
        body = _create(context, "  Sales  ", soul_md="  Soul\n\n", identity_md="\nIdentity\n").json()

        assert_that(body["display_name"], equal_to("Sales"))
        assert_that(body["soul_md"], equal_to("  Soul\n\n"))
        assert_that(body["identity_md"], equal_to("\nIdentity\n"))


def test_a_blank_name_or_soul_is_refused():
    with given(_given()) as context:
        assert_that(_create(context, "   ").status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
        assert_that(_create(context, soul_md="  \n").status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def _update(context, key="sales", version=1, **fields):
    return context.client.put(
        _url(context, f"/{key}"),
        json={**_body(**fields), "expected_version": version},
        headers=_auth(context),
    )


def test_editing_text_appends_a_version_and_keeps_the_old_one():
    with given(_given()) as context:
        _create(context)

        response = _update(context, soul_md="New soul")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["current_version"], equal_to(2))
        assert_that(response.json()["soul_md"], equal_to("New soul"))
        versions = context.client.get(_url(context, "/sales/versions"), headers=_auth(context)).json()
        assert_that([(item["version"], item["soul_md"]) for item in versions], equal_to([(2, "New soul"), (1, "Soul")]))


def test_editing_only_the_name_or_emoji_adds_no_version_and_keeps_the_key():
    with given(_given()) as context:
        _create(context)

        response = _update(context, name="Renamed", emoji="📈")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["current_version"], equal_to(1))
        assert_that(body["key"], equal_to("sales"))
        assert_that(body["display_name"], equal_to("Renamed"))
        assert_that(body["emoji"], equal_to("📈"))


def test_a_stale_edit_is_refused():
    with given(_given()) as context:
        _create(context)
        _update(context, soul_md="New soul")

        response = _update(context, version=1, soul_md="Stale")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_editing_the_default_is_refused():
    with given(_given()) as context:
        response = _update(context, key="default")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_editing_an_unknown_or_deleted_persona_is_not_found():
    with given(_given()) as context:
        _seed(context, "gone", deleted=True)

        assert_that(_update(context, key="gone").status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(_update(context, key="nosuch").status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_editing_while_running_is_refused():
    with given(_given()) as context:
        _create(context)
        _set_agent(context, status=AgentStatus.RUNNING)

        assert_that(_update(context, soul_md="New").status_code, equal_to(status.HTTP_409_CONFLICT))


def test_editing_still_works_when_the_flag_is_off():
    with given(_given(flag="false")) as context:
        _seed(context, "sales")

        assert_that(_update(context, soul_md="New").status_code, equal_to(status.HTTP_200_OK))


def test_changes_emit_agent_updated_without_any_prompt_text():
    with given(_given()) as context:
        _create(context)
        _update(context, soul_md="Secret soul text")

        events = _persona_events(context)

        assert_that(events, has_length(2))
        assert_that(
            events[0].payload["field_changes"], equal_to({"personas.sales": {"previous": None, "new": "created"}})
        )
        assert_that(
            events[1].payload["field_changes"], equal_to({"personas.sales": {"previous": None, "new": "updated"}})
        )
        assert_that("Secret soul text" in str(events[1].payload), equal_to(False))


def test_saving_identical_values_changes_nothing_and_emits_nothing():
    with given(_given()) as context:
        _create(context)

        response = _update(context)

        assert_that(response.json()["current_version"], equal_to(1))
        assert_that(_persona_events(context), has_length(1))


def _delete(context, key="sales"):
    return context.client.delete(_url(context, f"/{key}"), headers=_auth(context))


def _web_connection(context) -> CommunicationConnection:
    connection = CommunicationConnection(
        organization_id=context.organization.id,
        agent_id=context.agent.id,
        platform_key="web",
        display_name="Web Chat",
        credentials_encrypted="unused",
    )
    context.postgres_delegate.save(connection)
    return connection


def _inbound(context, connection, persona_id, name) -> UUID:
    envelope = NormalizedCommunicationEnvelope(
        provider_message_id=name,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id=f"user-{name}", type="DM", thread_id="main"),
        sender=CommunicationSender(id="user", display_name="User"),
        text="hello",
    )
    repository = context.injector.get(CommunicationDeliveryRepository)
    accepted = repository.accept_inbound(connection_id=connection.id, envelope=envelope)
    with Session(context.postgres_delegate.engine) as session:
        message = session.get_one(AgentChatMessage, accepted.message_id)
        message.persona_id = persona_id
        session.add(message)
        session.commit()
    return accepted.delivery_id


def _delivery(context, delivery_id) -> CommunicationDelivery:
    with Session(context.postgres_delegate.engine) as session:
        return session.get_one(CommunicationDelivery, delivery_id)


def test_deleting_a_persona_hides_it_but_keeps_its_row_and_versions():
    with given(_given()) as context:
        persona = _seed(context, "sales", versions=2)

        response = _delete(context)

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        keys = [item["key"] for item in context.client.get(_url(context), headers=_auth(context)).json()["personas"]]
        assert_that(keys, equal_to(["default"]))
        assert_that(context.client.get(_url(context, "/sales"), headers=_auth(context)).status_code, equal_to(404))
        with Session(context.postgres_delegate.engine) as session:
            stored = session.get_one(AgentPersona, persona.id)
            versions = session.exec(
                select(AgentPersonaVersion).where(AgentPersonaVersion.persona_id == persona.id)
            ).all()
        assert_that(stored.deleted_at, is_not(none()))
        assert_that(versions, has_length(2))


def test_a_deleted_personas_slot_is_freed_and_its_key_is_not_reused():
    with given(_given()) as context:
        for name in ("sales", "two", "three", "four", "five"):
            _create(context, name)
        assert_that(_create(context, "six").status_code, equal_to(status.HTTP_409_CONFLICT))

        _delete(context)

        response = _create(context, "sales")
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.json()["key"], equal_to("sales-2"))


def test_deleting_twice_or_an_unknown_persona_is_not_found():
    with given(_given()) as context:
        _seed(context, "sales")

        assert_that(_delete(context).status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(_delete(context).status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(_delete(context, "nosuch").status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_deleting_the_default_is_refused():
    with given(_given()) as context:
        assert_that(_delete(context, "default").status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_deleting_while_running_is_refused():
    with given(_given()) as context:
        _seed(context, "sales")
        _set_agent(context, status=AgentStatus.RUNNING)

        assert_that(_delete(context).status_code, equal_to(status.HTTP_409_CONFLICT))


def test_deleting_on_openclaw_is_refused_with_400():
    with given(_given(agent_type=AgentType.OPENCLAW)) as context:
        assert_that(_delete(context).status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_deleting_still_works_when_the_flag_is_off():
    with given(_given(flag="false")) as context:
        _seed(context, "sales")

        assert_that(_delete(context).status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_deleting_cancels_only_that_personas_open_deliveries():
    with given(_given()) as context:
        sales = _seed(context, "sales")
        lawyer = _seed(context, "lawyer")
        connection = _web_connection(context)
        _set_agent(context, status=AgentStatus.RUNNING)
        repository = context.injector.get(CommunicationDeliveryRepository)
        processing = _inbound(context, connection, sales.id, "processing")
        assert_that(repository.claim_next_inbound(agent_id=context.agent.id).delivery_id, equal_to(processing))
        pending = _inbound(context, connection, sales.id, "pending")
        other_persona = _inbound(context, connection, lawyer.id, "other")
        default = _inbound(context, connection, None, "default")
        _set_agent(context, status=AgentStatus.STOPPED)

        assert_that(_delete(context).status_code, equal_to(status.HTTP_204_NO_CONTENT))

        cancelled = _delivery(context, pending)
        assert_that(cancelled.status, equal_to(CommunicationDeliveryStatus.CANCELLED))
        assert_that(cancelled.completed_at, is_not(none()))
        flagged = _delivery(context, processing)
        assert_that(flagged.status, equal_to(CommunicationDeliveryStatus.PROCESSING))
        assert_that(flagged.cancel_requested_at, is_not(none()))
        for untouched in (other_persona, default):
            row = _delivery(context, untouched)
            assert_that(row.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(row.cancel_requested_at, none())


def test_a_flagged_processing_delivery_ends_cancelled_when_its_lease_expires():
    with given(_given()) as context:
        sales = _seed(context, "sales")
        connection = _web_connection(context)
        _set_agent(context, status=AgentStatus.RUNNING)
        repository = context.injector.get(CommunicationDeliveryRepository)
        delivery_id = _inbound(context, connection, sales.id, "processing")
        repository.claim_next_inbound(agent_id=context.agent.id)
        _set_agent(context, status=AgentStatus.STOPPED)

        _delete(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(CommunicationDelivery, delivery_id)
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(row)
            session.commit()
        repository.reclaim_expired_inbound(agent_id=context.agent.id)

        assert_that(_delivery(context, delivery_id).status, equal_to(CommunicationDeliveryStatus.CANCELLED))


def test_deleting_emits_agent_updated():
    with given(_given()) as context:
        _create(context)
        _delete(context)

        events = _persona_events(context)

        assert_that(
            events[-1].payload["field_changes"], equal_to({"personas.sales": {"previous": None, "new": "deleted"}})
        )


def _start(context):
    return context.client.post(f"{BASE}/{context.agent.id}/start", headers=_auth(context))


def _started_resources(context):
    k8s = context.injector.get(KubernetesClient)
    config_map = k8s.create_config_map.call_args.args[1]
    secret = k8s.create_secret.call_args.args[1]
    deployment = k8s.create_deployment.call_args.args[1]
    return config_map.data, secret.string_data, deployment.spec.template.spec


def _multiplex(pod) -> bool:
    return "GATEWAY_MULTIPLEX_PROFILES" in [env.name for env in pod.containers[0].env]


def test_starting_with_no_personas_is_unchanged():
    with given(_given()) as context:
        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        data, _, pod = _started_resources(context)

        assert_that("personas.json" in data, equal_to(False))
        assert_that("persona-setup.py" in data, equal_to(False))
        assert_that(_multiplex(pod), equal_to(False))


def test_starting_renders_each_personas_current_version_and_turns_on_multiplex():
    with given(_given()) as context:
        _seed(context, "sales", versions=2)
        _seed(context, "gone", deleted=True)

        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        data, _, pod = _started_resources(context)
        manifest = json.loads(data["personas.json"])
        assert_that(manifest["active"], equal_to([{"key": "sales"}]))
        assert_that(manifest["deleted_keys"], equal_to(["gone"]))
        assert_that(data["persona-sales-SOUL.md"].startswith("sales soul v2"), equal_to(True))
        assert_that(data["persona-sales-IDENTITY.md"], equal_to("sales identity v2"))
        assert_that("persona-gone-SOUL.md" in data, equal_to(False))
        assert_that(_multiplex(pod), equal_to(True))


def test_the_flag_being_off_does_not_stop_existing_personas_from_running():
    with given(_given(flag="false")) as context:
        _seed(context, "sales")

        _start(context)

        assert_that(_multiplex(_started_resources(context)[2]), equal_to(True))


def test_deleting_the_last_persona_turns_off_multiplex_but_still_cleans_up():
    with given(_given()) as context:
        _seed(context, "gone", deleted=True)

        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        data, _, pod = _started_resources(context)
        manifest = json.loads(data["personas.json"])
        assert_that(manifest["active"], equal_to([]))
        assert_that(manifest["deleted_keys"], equal_to(["gone"]))
        assert_that(_multiplex(pod), equal_to(False))


def test_an_openclaw_agent_never_gets_persona_files():
    with given(_given(agent_type=AgentType.OPENCLAW)) as context:
        _seed(context, "sales")

        _start(context)

        assert_that("personas.json" in _started_resources(context)[0], equal_to(False))


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("telegram", {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"}),
        ("slack", {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOW_ALL_USERS", "AGENTBARN_SLACK_DM_POLICY"}),
    ],
)
def test_a_connected_platforms_settings_reach_the_default_env_names(platform, expected):
    with given(_given()) as context:
        credentials = {"bot_token": "123:token", "app_token": "xapp-token"}
        settings = {"channel_ids": ["C1"], "group_policy": "allowlist", "dm_policy": "off"}
        if platform == "telegram":
            credentials = {"bot_token": "123:token"}
            settings = {"allowed_chat_ids": ["-1001"], "dm_policy": "allowlist", "allowed_user_ids": ["111"]}
        context.postgres_delegate.save(
            CommunicationConnection(
                organization_id=context.organization.id,
                agent_id=context.agent.id,
                platform_key=platform,
                display_name="Native",
                settings=settings,
                credentials_encrypted=encrypt_token(json.dumps(credentials), TEST_ENCRYPTION_KEY),
            )
        )
        _seed(context, "sales")

        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        data, secret, _ = _started_resources(context)
        names = set(json.loads(data["personas.json"])["default_env_names"])
        platform_prefixes = ("SLACK_", "AGENTBARN_SLACK_", "TELEGRAM_")
        assert_that(names, equal_to({name for name in secret if name.startswith(platform_prefixes)}))
        assert_that(expected <= names, equal_to(True))


def test_a_secret_value_with_a_newline_refuses_the_start_naming_only_the_key():
    with given(
        [
            set_env_variable({"AGENT_FIRECRAWL_API_KEY": "line1\nline2", "AGENT_FIRECRAWL_BASE_URL": "http://fc"}),
            *_given(),
        ]
    ) as context:
        _seed(context, "sales")
        k8s = context.injector.get(KubernetesClient)

        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("FIRECRAWL_API_KEY"))
        assert_that("line1" in response.text, equal_to(False))
        assert_that(k8s.create_deployment.called, equal_to(False))
        assert_that(k8s.delete_config_map.called, equal_to(False))


def test_a_secret_value_with_a_newline_is_ignored_without_personas():
    with given(
        [
            set_env_variable({"AGENT_FIRECRAWL_API_KEY": "line1\nline2", "AGENT_FIRECRAWL_BASE_URL": "http://fc"}),
            *_given(),
        ]
    ) as context:
        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))


def test_an_oversized_config_map_refuses_the_start_with_personas():
    with given(_given(soul_md="x" * 1_100_000)) as context:
        _seed(context, "sales")
        k8s = context.injector.get(KubernetesClient)

        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("too large"))
        assert_that(k8s.delete_config_map.called, equal_to(False))
