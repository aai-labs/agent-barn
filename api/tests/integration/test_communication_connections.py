import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from fastapi import status
from hamcrest import (
    all_of,
    assert_that,
    close_to,
    contains_inanyorder,
    contains_string,
    equal_to,
    greater_than_or_equal_to,
    has_entries,
    has_key,
    has_length,
    is_,
    none,
    not_,
    not_none,
)
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationJournalEntry,
    CommunicationJournalStage,
    CommunicationSender,
    ConnectionObservedStatus,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    RuntimeReplyCreate,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.events.models import OutboxMessage
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    TEST_SLACK_APP_TOKEN,
    TEST_SLACK_BOT_TOKEN,
    TEST_TELEGRAM_BOT_TOKEN,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
            "SKIP_TELEGRAM_TOKEN_VALIDATION": "true",
            "SKIP_DISCORD_TOKEN_VALIDATION": "true",
            "SKIP_TEAMS_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
]

_GIVEN_WITH_HERMES_AGENT = [*_GIVEN[:-1], there_is_an_agent(agent_type=AgentType.HERMES)]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _base_for_agent(context, agent_id: UUID) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{agent_id}/connections"


def _base(context) -> str:
    return _base_for_agent(context, context.agent.id)


def _slack_payload() -> dict:
    return {
        "platform_key": "slack",
        "display_name": "Slack",
        "credentials": {
            "bot_token": TEST_SLACK_BOT_TOKEN,
            "app_token": TEST_SLACK_APP_TOKEN,
        },
    }


def _telegram_payload() -> dict:
    return {
        "platform_key": "telegram",
        "display_name": "Telegram",
        "credentials": {"bot_token": TEST_TELEGRAM_BOT_TOKEN},
    }


def _discord_payload(name: str = "Community Discord", bot_token: str = "token-one") -> dict:
    return {
        "platform_key": "discord",
        "display_name": name,
        "settings": {"guild_ids": ["guild-one"]},
        "credentials": {"bot_token": bot_token},
    }


def test_platform_catalog_lists_the_shipped_plugins() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list the shipped Communication Platforms"):
            response = client.get(
                f"/api/v1/organizations/{context.organization.id}/communication-platforms",
                headers=_auth(context),
            )

        with then("the stable plugin catalogue is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            catalogue = response.json()
            assert_that(
                [item["key"] for item in catalogue],
                contains_inanyorder("discord", "slack", "teams", "telegram"),
            )
            hints = {item["key"]: item["setup_hint"] for item in catalogue}
            assert_that(
                hints["slack"],
                all_of(
                    contains_string("xoxb-"),
                    contains_string("xapp-"),
                    contains_string("connections:write"),
                    contains_string("channels:read"),
                    contains_string("users:read"),
                ),
            )
            assert_that(
                hints["discord"],
                all_of(
                    contains_string("Message Content Intent"),
                    contains_string("View Channels"),
                    contains_string("Read Message History"),
                    contains_string("Developer Mode"),
                ),
            )
            assert_that(
                hints["telegram"],
                all_of(
                    contains_string("@BotFather"),
                    contains_string("/newbot"),
                    contains_string("getUpdates"),
                    contains_string("/setprivacy"),
                    contains_string("webhook"),
                ),
            )


def test_list_connections_without_authentication_returns_401() -> None:
    with given(_GIVEN) as context:
        with when("I list Communication Connections without a token"):
            response = context.client.get(_base(context))

        with then("authentication is required"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_create_connection_rejects_unknown_platform() -> None:
    with given(_GIVEN) as context:
        payload = _discord_payload()
        payload["platform_key"] = "carrier-pigeon"

        with when("I create a Connection for a plugin that is not shipped"):
            response = context.client.post(_base(context), json=payload, headers=_auth(context))

        with then("the platform key fails domain validation"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_connection_rejects_incomplete_payload() -> None:
    with given(_GIVEN) as context:
        with when("I omit the required credentials"):
            response = context.client.post(
                _base(context),
                json={"platform_key": "discord", "display_name": "Incomplete"},
                headers=_auth(context),
            )

        with then("request validation reports the missing field"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_connection_requires_agent_update_permission() -> None:
    with given(_GIVEN) as context:
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

        with when("I create a Connection without Agent update permission"):
            response = context.client.post(
                _base(context),
                json=_discord_payload(),
                headers=_auth(context),
            )

        with then("the visible Agent rejects the mutation"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_other_organization_agent_is_hidden() -> None:
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        with when("I list Connections through the original Organization route"):
            response = context.client.get(_base(context), headers=_auth(context))

        with then("the cross-Organization Agent is hidden"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_agent_can_have_multiple_connections_for_the_same_platform() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create two Discord connections"):
            first = client.post(_base(context), json=_discord_payload(), headers=_auth(context))
            second = client.post(
                _base(context),
                json=_discord_payload("Partner Discord", "token-two"),
                headers=_auth(context),
            )
            listed = client.get(_base(context), headers=_auth(context))

        with then("both connections belong to the Agent without exposing credentials"):
            assert_that(first.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(second.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(len(listed.json()), equal_to(2))
            assert_that(first.json(), has_entries(platform_key="discord", display_name="Community Discord", revision=1))
            assert_that(first.json(), not_(has_key("credentials")))


def test_retiring_agent_releases_all_platform_credentials() -> None:
    with given(_GIVEN_WITH_HERMES_AGENT) as context:
        client: TestClient = context.client
        retired_agent_id = context.agent.id
        retired_agent_connections = _base_for_agent(context, retired_agent_id)

        with when("I retire the Hermes Agent and assign its tokens to OpenClaw"):
            slack = client.post(
                retired_agent_connections,
                json=_slack_payload(),
                headers=_auth(context),
            )
            telegram = client.post(
                retired_agent_connections,
                json=_telegram_payload(),
                headers=_auth(context),
            )
            retired = client.delete(
                f"/api/v1/organizations/{context.organization.id}/agents/{retired_agent_id}",
                headers=_auth(context),
            )
            there_is_an_agent(name="OpenClaw Agent", agent_type=AgentType.OPENCLAW)(context)
            openclaw_connections = _base(context)
            reassigned_slack = client.post(
                openclaw_connections,
                json=_slack_payload(),
                headers=_auth(context),
            )
            reassigned_telegram = client.post(
                openclaw_connections,
                json=_telegram_payload(),
                headers=_auth(context),
            )

        with then("retiring the Agent releases both platform tokens"):
            assert_that(slack.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(telegram.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(retired.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(reassigned_slack.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(reassigned_telegram.status_code, equal_to(status.HTTP_201_CREATED))


def test_duplicate_active_connection_name_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        client.post(_base(context), json=_discord_payload(), headers=_auth(context))

        with when("I reuse the active display name with different casing"):
            response = client.post(
                _base(context),
                json=_discord_payload("community discord", "token-two"),
                headers=_auth(context),
            )

        with then("the database-backed invariant returns a conflict"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_stale_connection_update_returns_conflict() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        url = f"{_base(context)}/{created['id']}"
        current = client.patch(
            url,
            json={"revision": 1, "display_name": "Updated Discord"},
            headers=_auth(context),
        )

        with when("I update using the superseded revision"):
            stale = client.patch(
                url,
                json={"revision": 1, "enabled": False},
                headers=_auth(context),
            )

        with then("optimistic concurrency rejects the stale write"):
            assert_that(current.status_code, equal_to(status.HTTP_200_OK))
            assert_that(current.json()["revision"], equal_to(2))
            assert_that(stale.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_connection_settings_name_and_credentials_can_be_updated() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()

        with when("I update every editable schema-driven field"):
            response = client.patch(
                f"{_base(context)}/{created['id']}",
                json={
                    "revision": created["revision"],
                    "display_name": "Renamed Discord",
                    "settings": {"guild_ids": ["guild-two"]},
                    "credentials": {"bot_token": "rotated-token"},
                },
                headers=_auth(context),
            )

        with then("the public configuration changes without exposing credentials"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(
                    display_name="Renamed Discord",
                    settings={
                        "guild_ids": ["guild-two"],
                        "allowed_channel_ids": [],
                        "allowed_user_ids": [],
                        "allowed_role_ids": [],
                        "group_policy": "allowlist",
                        "dm_policy": "off",
                        "require_mention": True,
                        "home_channel_id": None,
                    },
                    external_identity="validation-skipped",
                    revision=2,
                ),
            )
            assert_that(response.json(), not_(has_key("credentials")))


def test_unknown_connection_update_returns_404() -> None:
    with given(_GIVEN) as context:
        with when("I update a Connection that does not exist"):
            response = context.client.patch(
                f"{_base(context)}/00000000-0000-0000-0000-000000000099",
                json={"revision": 1, "enabled": False},
                headers=_auth(context),
            )

        with then("the subordinate resource is hidden as not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_ingress_lease_allows_only_one_gateway_replica() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        repository = context.injector.get(CommunicationConnectionRepository)

        with when("two gateway replicas contend for one Connection"):
            first = repository.claim_ingress_lease(connection_id, "gateway-a")
            second = repository.claim_ingress_lease(connection_id, "gateway-b")
            repository.release_ingress_lease(connection_id, "gateway-a")
            after_release = repository.claim_ingress_lease(connection_id, "gateway-b")

        with then("the lease serializes provider ownership and can be transferred"):
            assert_that(first, equal_to(True))
            assert_that(second, equal_to(False))
            assert_that(after_release, equal_to(True))


def test_connection_diagnostics_and_reconnect_preserve_safe_operational_history() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        repository = context.injector.get(CommunicationConnectionRepository)

        repository.record_health(
            connection_id,
            ConnectionObservedStatus.ERROR,
            error_code="authorization-token",
            error_message="provider rejected an invalid credential",
        )

        with when("I inspect the Connection and request a reconnect"):
            diagnostics = client.get(f"{_base(context)}/{connection_id}/summary", headers=_auth(context))
            reconnect = client.post(f"{_base(context)}/{connection_id}/reconnect", headers=_auth(context))
            journal_page = client.get(
                f"{_base(context)}/{connection_id}/journal?page=1&page_size=2&kind=connection", headers=_auth(context)
            )
            delivery_page = client.get(
                f"{_base(context)}/{connection_id}/journal?kind=delivery", headers=_auth(context)
            )

        with then("the API separates health from delivery and records safe recovery history"):
            assert_that(diagnostics.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                diagnostics.json(),
                has_entries(
                    provider_connectivity="ERROR",
                    end_to_end_health="degraded",
                    delivery_counts=has_entries(total=0),
                ),
            )
            assert_that(reconnect.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(journal_page.status_code, equal_to(status.HTTP_200_OK))
            assert_that(delivery_page.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                reconnect.json()["connection"],
                has_entries(observed_status="CONNECTING", revision=2),
            )

            with Session(context.postgres_delegate.engine) as session:
                journal = list(
                    session.exec(
                        select(CommunicationJournalEntry)
                        .where(CommunicationJournalEntry.connection_id == connection_id)
                        .order_by(col(CommunicationJournalEntry.occurred_at))
                    ).all()
                )
                events = list(
                    session.exec(
                        select(OutboxMessage)
                        .where(OutboxMessage.organization_id == context.organization.id)
                        .order_by(col(OutboxMessage.created_at))
                    ).all()
                )

            assert_that(
                [getattr(entry.stage, "value", entry.stage) for entry in journal],
                equal_to(["connection_error", "connection_connecting", "reconnect_requested"]),
            )
            assert_that(journal[0].error_code, equal_to("REDACTED"))
            assert_that(journal[0].error_summary, equal_to("Provider error details were redacted"))
            assert_that(len(events), equal_to(3))
            assert_that(str(events[0].payload), not_(contains_string("invalid credential")))
            assert_that(str(diagnostics.json()), not_(contains_string("provider rejected")))
            assert_that(journal_page.json(), has_entries(page=1, page_size=2, total=3))
            assert_that(len(journal_page.json()["items"]), equal_to(2))
            assert_that(str(journal_page.json()), not_(contains_string("provider rejected")))
            assert_that(delivery_page.json(), has_entries(total=0, items=[]))


def test_structured_provider_diagnostics_are_retained_without_provider_secrets() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_telegram_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        repository = context.injector.get(CommunicationConnectionRepository)
        request = httpx.Request(
            "GET",
            "https://api.telegram.org/botsecret-token/getUpdates",
        )
        response = httpx.Response(
            503,
            request=request,
            headers={"Retry-After": "30", "X-Request-ID": "telegram-request-123"},
            json={"ok": False, "error": "service_unavailable"},
        )
        normalized = normalize_communication_error(
            httpx.HTTPStatusError("503 provider error for a botsecret-token URL", request=request, response=response),
            operation="poll_updates",
        )

        repository.record_health(
            connection_id,
            ConnectionObservedStatus.ERROR,
            error_code=normalized.code,
            error_message=normalized.summary,
            error_details=normalized.details,
        )

        summary = client.get(f"{_base(context)}/{connection_id}/summary", headers=_auth(context))
        journal = client.get(
            f"{_base(context)}/{connection_id}/journal?kind=connection",
            headers=_auth(context),
        )
        connection_list = client.get(_base(context), headers=_auth(context))

        expected_details = has_entries(
            category="provider_unavailable",
            operation="poll_updates",
            http_status=503,
            provider_code="service_unavailable",
            retryable=True,
            retry_after_seconds=30,
            request_id="telegram-request-123",
        )
        expected_summary = "The provider is temporarily unavailable (HTTP 503, service_unavailable)"

        assert_that(summary.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            summary.json()["connection"],
            has_entries(
                last_error_code="PROVIDER_UNAVAILABLE",
                last_error_message=expected_summary,
                last_error_details=expected_details,
            ),
        )
        assert_that(
            summary.json()["recent_failures"][0],
            has_entries(
                error_code="PROVIDER_UNAVAILABLE",
                error_summary=expected_summary,
                error_details=expected_details,
            ),
        )
        assert_that(
            journal.json()["items"][0],
            has_entries(
                error_code="PROVIDER_UNAVAILABLE",
                error_summary=expected_summary,
                error_details=expected_details,
            ),
        )
        assert_that(
            connection_list.json()[0],
            has_entries(
                last_error_code="PROVIDER_UNAVAILABLE",
                last_error_message=expected_summary,
                last_error_details=expected_details,
            ),
        )
        assert_that(str(summary.json()), not_(contains_string("botsecret-token")))


def test_diagnostics_read_does_not_grant_connection_recovery_permission() -> None:
    with given(_GIVEN) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_url = f"{_base(context)}/{created['id']}"
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

        with when("a viewer reads diagnostics and activity while attempting a reconnect"):
            diagnostics = client.get(f"{connection_url}/summary", headers=_auth(context))
            journal_page = client.get(f"{connection_url}/journal", headers=_auth(context))
            reconnect = client.post(f"{connection_url}/reconnect", headers=_auth(context))

        with then("read access remains available while recovery requires Agent update"):
            assert_that(diagnostics.status_code, equal_to(status.HTTP_200_OK))
            assert_that(journal_page.status_code, equal_to(status.HTTP_200_OK))
            assert_that(reconnect.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def _envelope(message_id: str) -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id=message_id,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id="channel-one", type="CHANNEL", thread_id="thread-one"),
        sender=CommunicationSender(id="person-one", display_name="Person One"),
        text=f"message {message_id}",
    )


def test_connection_summary_reports_richer_health_and_delivery_signals() -> None:
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        connections = context.injector.get(CommunicationConnectionRepository)
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        connections.record_health(connection_id, ConnectionObservedStatus.CONNECTED)

        succeeded = deliveries.accept_inbound(connection_id=connection_id, envelope=_envelope("succeeded"))
        claimed = deliveries.claim_next_inbound(agent_id=context.agent.id)
        assert_that(
            claimed.delivery_id if claimed is not None else None,
            equal_to(succeeded.delivery_id),
        )
        assert_that(
            deliveries.complete_runtime_delivery(
                claimed.delivery_id if claimed is not None else UUID(int=0),
                agent_id=context.agent.id,
                succeeded=True,
            ),
            is_(True),
        )

        for message_id in ("failed-one", "failed-two"):
            accepted = deliveries.accept_inbound(connection_id=connection_id, envelope=_envelope(message_id))
            claimed = deliveries.claim_next_inbound(agent_id=context.agent.id)
            assert_that(
                claimed.delivery_id if claimed is not None else None,
                equal_to(accepted.delivery_id),
            )
            assert_that(
                deliveries.complete_runtime_delivery(
                    claimed.delivery_id if claimed is not None else UUID(int=0),
                    agent_id=context.agent.id,
                    succeeded=False,
                    error_code="model_error",
                    error_message="the model failed",
                    max_attempts=1,
                ),
                is_(True),
            )

        deliveries.accept_inbound(connection_id=connection_id, envelope=_envelope("still-pending"))

        connections.record_health(
            connection_id,
            ConnectionObservedStatus.ERROR,
            error_code="authorization-token",
            error_message="provider rejected the bearer token",
        )

        with when("I inspect the Connection summary"):
            summary = client.get(f"{_base(context)}/{connection_id}/summary", headers=_auth(context))

        with then("aggregate health and delivery-trend signals are reported"):
            assert_that(summary.status_code, equal_to(status.HTTP_200_OK))
            body = summary.json()
            assert_that(body["last_successful_connection_at"], not_none())
            assert_that(body["current_error_age_seconds"], not_none())
            assert_that(body["current_error_age_seconds"], greater_than_or_equal_to(0.0))
            assert_that(body["consecutive_failure_count"], equal_to(2))
            assert_that(body["delivery_success_rate"], close_to(1 / 3, 0.001))
            assert_that(body["oldest_pending_delivery_age_seconds"], not_none())
            assert_that(
                [state["status"] for state in body["connection_history"]],
                equal_to(["ERROR", "CONNECTED"]),
            )
            assert_that(str(body), not_(contains_string("provider rejected")))


def test_diagnostics_and_journal_reject_windows_over_90_days() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = created["id"]
        invalid_window = "2025-01-01T00:00:00Z"
        window_end = "2025-04-02T00:00:00Z"

        summary = context.client.get(
            f"{_base(context)}/{connection_id}/summary?since={invalid_window}&until={window_end}",
            headers=_auth(context),
        )
        journal = context.client.get(
            f"{_base(context)}/{connection_id}/journal?kind=connection&since={invalid_window}&until={window_end}",
            headers=_auth(context),
        )

        assert_that(summary.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(journal.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(summary.json()["detail"], equal_to("Diagnostics window cannot exceed 90 days"))
        assert_that(journal.json()["detail"], equal_to("Diagnostics window cannot exceed 90 days"))


def test_connection_and_journal_reads_redact_legacy_error_details() -> None:
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        operations = context.injector.get(CommunicationOperationalRepository)
        legacy_entry = operations.record_journal(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            connection_id=connection_id,
            stage=CommunicationJournalStage.CONNECTION_ERROR,
            error_code="provider_error",
            error_summary="Provider error details were redacted",
        )

        with Session(context.injector.get(PostgresRepositoryDelegate).engine, expire_on_commit=False) as session:
            connection = session.get(CommunicationConnection, connection_id)
            if connection is None:
                raise AssertionError("Connection was not persisted")
            connection.last_error_code = "authorization-token"
            connection.last_error_message = "provider returned confidential details"
            session.add(connection)
            journal_entry = session.get(CommunicationJournalEntry, legacy_entry.id)
            if journal_entry is None:
                raise AssertionError("Journal entry was not persisted")
            journal_entry.error_code = "authorization-token"
            journal_entry.error_summary = "provider returned confidential details"
            session.add(journal_entry)
            session.commit()

        with when("I read a Connection and its legacy journal entry"):
            connection_read = client.get(_base(context), headers=_auth(context))
            journal_read = client.get(
                f"{_base(context)}/{connection_id}/journal?kind=connection",
                headers=_auth(context),
            )

        with then("legacy error details are redacted at every read boundary"):
            assert_that(connection_read.status_code, equal_to(status.HTTP_200_OK))
            connection_items = connection_read.json()
            matching_connection = next(
                (item for item in connection_items if item.get("id") == str(connection_id)),
                None,
            )
            if matching_connection is None:
                raise AssertionError("Connection was not returned by the list endpoint")
            assert_that(
                matching_connection,
                has_entries(
                    last_error_code="REDACTED",
                    last_error_message="Provider error details were redacted",
                ),
            )
            assert_that(journal_read.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                journal_read.json()["items"][0],
                has_entries(
                    error_code="REDACTED",
                    error_summary="Provider error details were redacted",
                ),
            )


def test_communication_journal_pruning_keeps_the_configured_retention_window_bounded() -> None:
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        operations = context.injector.get(CommunicationOperationalRepository)
        now = datetime.now(UTC)

        operations.record_journal(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            connection_id=connection_id,
            stage=CommunicationJournalStage.CONNECTION_ERROR,
            occurred_at=now - timedelta(days=40),
            error_code="provider_error",
            error_summary="Provider error details were redacted",
        )
        operations.record_journal(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            connection_id=connection_id,
            stage=CommunicationJournalStage.CONNECTION_CONNECTED,
            occurred_at=now - timedelta(days=1),
        )

        with when("the retention sweep runs for a thirty-day window"):
            removed = operations.prune_journal(retention_days=30)

        with then("expired history is removed while recent operational history remains"):
            assert_that(removed, equal_to(1))
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                remaining = list(
                    session.exec(
                        select(CommunicationJournalEntry).where(
                            CommunicationJournalEntry.connection_id == connection_id
                        )
                    ).all()
                )
            assert_that(remaining, has_length(1))
            assert_that(remaining[0].stage, equal_to(CommunicationJournalStage.CONNECTION_CONNECTED))


def test_journal_filters_narrow_by_stage_error_direction_and_delivery() -> None:
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        created = client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        # An inbound Delivery that stays queued, plus an outbound reply that
        # gets dead-lettered, so direction and retry filters have two distinct
        # Deliveries to tell apart.
        accepted = deliveries.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))
        outbound_id = deliveries.enqueue_runtime_reply(
            agent_id=context.agent.id,
            source_delivery_id=accepted.delivery_id,
            reply=RuntimeReplyCreate(idempotency_key="reply-1", text="retry me"),
        )
        claimed = deliveries.claim_next_outbound()
        assert_that(claimed, is_(not_(none())))
        assert_that(
            deliveries.complete_outbound(
                outbound_id,
                error_code="provider_timeout",
                error_message="temporary provider failure",
                max_attempts=1,
            ),
            is_(True),
        )

        base = f"{_base(context)}/{connection_id}/journal"

        with when("I filter Connection activity along several axes"):
            failed_only = client.get(f"{base}?kind=delivery&failed_only=true", headers=_auth(context))
            retryable_before = client.get(f"{base}?kind=delivery&retryable_only=true", headers=_auth(context))
            inbound_direction = client.get(f"{base}?kind=delivery&direction=INBOUND", headers=_auth(context))
            outbound_direction = client.get(f"{base}?kind=delivery&direction=OUTBOUND", headers=_auth(context))
            by_stage = client.get(f"{base}?kind=delivery&stage=dead_lettered", headers=_auth(context))
            by_delivery = client.get(
                f"{base}?kind=delivery&delivery_id={outbound_id}&order=asc", headers=_auth(context)
            )

            retry = client.post(
                f"{_base(context)}/{connection_id}/deliveries/{outbound_id}/retry",
                headers=_auth(context),
            )
            retryable_after = client.get(f"{base}?kind=delivery&retryable_only=true", headers=_auth(context))

        with then("each filter composes correctly against the joined Delivery state"):
            assert_that(failed_only.json()["total"], equal_to(2))
            failed_stages = {item["stage"] for item in failed_only.json()["items"]}
            assert_that(failed_stages, equal_to({"provider_delivery_attempted", "dead_lettered"}))
            assert_that(
                all(item["error_code"] == "provider_timeout" for item in failed_only.json()["items"]), is_(True)
            )

            assert_that(retryable_before.json()["total"], equal_to(1))
            assert_that(retryable_before.json()["items"][0]["stage"], equal_to("dead_lettered"))

            assert_that(inbound_direction.json()["total"], equal_to(1))
            assert_that(inbound_direction.json()["items"][0]["stage"], equal_to("queued"))
            assert_that(outbound_direction.json()["total"], equal_to(4))

            assert_that(by_stage.json()["total"], equal_to(1))

            by_delivery_stages = [item["stage"] for item in by_delivery.json()["items"]]
            assert_that(
                by_delivery_stages,
                equal_to(
                    ["reply_queued", "provider_delivery_attempted", "provider_delivery_attempted", "dead_lettered"]
                ),
            )
            assert_that(by_delivery.json()["items"], has_length(len(by_delivery_stages)))

            assert_that(retry.status_code, equal_to(status.HTTP_202_ACCEPTED))
            # The dead-lettered Delivery Transition is still there, but the Delivery it
            # belongs to is no longer dead-lettered, so it drops off retryable_only.
            assert_that(retryable_after.json()["total"], equal_to(0))


def test_retryable_journal_filter_excludes_dead_lettered_inbound_deliveries() -> None:
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        created = context.client.post(_base(context), json=_discord_payload(), headers=_auth(context)).json()
        connection_id = UUID(created["id"])
        deliveries = context.injector.get(CommunicationDeliveryRepository)
        accepted = deliveries.accept_inbound(connection_id=connection_id, envelope=_envelope("inbound-dead-letter"))
        claimed = deliveries.claim_next_inbound(agent_id=context.agent.id)
        assert_that(claimed, is_(not_(none())))
        assert_that(
            deliveries.complete_runtime_delivery(
                claimed.delivery_id if claimed is not None else UUID(int=0),
                agent_id=context.agent.id,
                succeeded=False,
                error_code="runtime_timeout",
                error_message="runtime failed",
                max_attempts=1,
            ),
            is_(True),
        )

        response = context.client.get(
            f"{_base(context)}/{connection_id}/journal?kind=delivery&retryable_only=true",
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["total"], equal_to(0))
        assert_that(accepted.delivery_id, is_(not_none()))


def _teams_payload(name: str = "Microsoft Teams") -> dict:
    return {
        "platform_key": "teams",
        "display_name": name,
        "credentials": {
            "app_id": "11111111-1111-4111-8111-111111111111",
            "app_password": "placeholder",
            "tenant_id": "22222222-2222-4222-8222-222222222222",
        },
    }


def test_teams_connection_serves_a_downloadable_app_package() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_teams_payload(), headers=_auth(context))
        connection_id = created.json()["id"]

        with when("I download the Teams app package for the Connection"):
            response = context.client.get(
                f"{_base(context)}/{connection_id}/app-package",
                headers=_auth(context),
            )

        with then("a Teams-installable zip is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.headers["content-type"], equal_to("application/zip"))
            assert_that(response.headers["content-disposition"], contains_string(".zip"))
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert_that(sorted(archive.namelist()), equal_to(["color.png", "manifest.json", "outline.png"]))
                manifest = json.loads(archive.read("manifest.json"))
            assert_that(manifest["bots"][0]["botId"], equal_to("11111111-1111-4111-8111-111111111111"))
            assert_that("placeholder" in archive_text(response.content), equal_to(False))


def test_app_package_is_rejected_for_a_platform_without_provisioning() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_discord_payload(), headers=_auth(context))
        connection_id = created.json()["id"]

        with when("I request an app package for Discord"):
            response = context.client.get(
                f"{_base(context)}/{connection_id}/app-package",
                headers=_auth(context),
            )

        with then("the platform reports it provides no installable package"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_app_package_is_concealed_across_organizations() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(_base(context), json=_teams_payload(), headers=_auth(context))
        connection_id = created.json()["id"]
        other_agent_id = uuid4()

        with when("I request the package through another Agent's path"):
            response = context.client.get(
                f"{_base_for_agent(context, other_agent_id)}/{connection_id}/app-package",
                headers=_auth(context),
            )

        with then("the Connection is concealed"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def archive_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.read("manifest.json").decode()


def test_app_package_is_named_after_the_agent_not_the_connection() -> None:
    with given(_GIVEN) as context:
        created = context.client.post(
            _base(context),
            json=_teams_payload(name="Microsoft Teams"),
            headers=_auth(context),
        )
        connection_id = created.json()["id"]

        with when("I download the package for a Connection labelled with the platform name"):
            response = context.client.get(
                f"{_base(context)}/{connection_id}/app-package",
                headers=_auth(context),
            )

        with then("the bot is named after the Agent, so two Agents never collide in Teams"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            manifest = json.loads(archive_text(response.content))
            assert_that(manifest["name"]["short"], equal_to(context.agent.name))
            assert_that(manifest["name"]["short"], not_(equal_to("Microsoft Teams")))
            slug = context.agent.name.lower().replace(" ", "-")
            assert_that(response.headers["content-disposition"], contains_string(f"{slug}-teams-app.zip"))
