from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length
from sqlalchemy import text
from sqlmodel import Session, col, select

from api.domains.agent_settings.models import OrganizationAgentSettings
from api.domains.agents.models import Agent
from api.domains.events.models import OutboxMessage
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    ProviderType,
)
from api.domains.organizations.models import Organization
from api.domains.usage.models import SuspensionReason
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.llm_provider_keys.checker import LlmProviderKeyChecker
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/llm-providers"
ADMIN_NAME = "Platform Person"
EVENT = "platform.llm_provider.organizations_changed"
OPENROUTER_MODEL = "openai/gpt-4o"
ORGANIZATIONS_NOT_TAKEN = 'Organizations are listed only for "all_except" and "only". Nothing was saved.'
ACCESS_CHOICE = 'Organization access is "all", "none", "all_except" or "only". Nothing was saved.'
UNKNOWN_ORGANIZATION = "One of these organizations does not exist. Nothing was saved."
TOO_MANY_ORGANIZATIONS = "A provider can list at most 1000 organizations. Nothing was saved."
NOT_FOUND = "That connection does not exist."
CREATED_EVENT = "platform.llm_provider.created"
NEW_KEY = "sk-ant-new-key-g7h8"


def _setup(*steps):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "SKIP_SLACK_TOKEN_VALIDATION": "true"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        *steps,
    ]


def admin(context):
    organization = context.organization
    del context.organization
    try:
        user_id = uuid7()
        there_is_a_user(id=user_id, name=ADMIN_NAME, email=f"platform-{user_id}@example.com", is_platform_admin=True)(
            context
        )
        there_is_an_access_token_for_user(user_id)(context)
    finally:
        context.organization = organization


def anthropic_connected(context):
    with _session(context) as session:
        session.add(LlmProviderConnection(slug="anthropic", name="Anthropic", provider_type=ProviderType.ANTHROPIC))
        session.commit()


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _session(context) -> Session:
    return Session(context.injector.get(PostgresRepositoryDelegate).engine)


def _organization(context, name: str, allowed_models: list[str] | None = None) -> UUID:
    organization = Organization(name=name, allowed_models=allowed_models or [])
    with _session(context) as session:
        session.add(organization)
        session.commit()
        return organization.id


def _url(slug: str) -> str:
    return f"{BASE}/{slug}/organizations"


def _put(context, slug: str, access: str, ids: list, headers=None):
    return context.client.put(
        _url(slug),
        json={"organization_access": access, "organization_ids": [str(organization_id) for organization_id in ids]},
        headers=headers or auth(context),
    )


def _stored(context, slug: str) -> tuple[str, list[UUID]]:
    with _session(context) as session:
        connection = session.exec(select(LlmProviderConnection).where(LlmProviderConnection.slug == slug)).one()
        listed = session.exec(
            select(LlmProviderConnectionOrganization.organization_id).where(
                LlmProviderConnectionOrganization.connection_id == connection.id
            )
        ).all()
        return connection.organization_access.value, sorted(listed, key=str)


def _events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == EVENT)).all())


def _read_only(context) -> dict:
    created = context.client.post(
        "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
    )
    return {"Authorization": f"Bearer {created.json()['token']}"}


def test_an_organization_owner_cannot_read_or_replace_a_connections_access():
    with given(_setup()) as context:
        read = context.client.get(_url("openrouter"), headers=auth(context))
        replace = _put(context, "openrouter", "none", [])

        assert_that((read.status_code, replace.status_code), equal_to((403, 403)))
        assert_that(_stored(context, "openrouter"), equal_to(("all", [])))


def test_a_read_only_api_key_of_a_platform_admin_can_read_but_not_replace_access():
    with given(_setup(admin)) as context:
        read_only = _read_only(context)

        read = context.client.get(_url("openrouter"), headers=read_only)
        replace = _put(context, "openrouter", "none", [], headers=read_only)

        assert_that((read.status_code, replace.status_code), equal_to((200, 403)))
        assert_that(_stored(context, "openrouter"), equal_to(("all", [])))


def test_every_connection_starts_open_to_all_organizations():
    with given(_setup(admin)) as context:
        response = context.client.get(_url("openrouter"), headers=auth(context))

        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), equal_to({"organization_access": "all", "organizations": []}))


@pytest.mark.parametrize("slug", ["mistral", "anthropic"])
def test_a_missing_or_deleted_connection_is_not_found(slug):
    with given(_setup(admin, anthropic_connected)) as context:
        with _session(context) as session:
            session.connection().execute(
                text("UPDATE llm_provider_connection SET deleted_at = now() WHERE slug = 'anthropic'")
            )
            session.commit()

        read = context.client.get(_url(slug), headers=auth(context))
        replace = _put(context, slug, "none", [])

        assert_that((read.status_code, replace.status_code), equal_to((404, 404)))
        assert_that((read.json()["detail"], replace.json()["detail"]), equal_to((NOT_FOUND, NOT_FOUND)))


def test_a_platform_admin_opens_a_connection_only_to_listed_organizations():
    with given(_setup(admin, anthropic_connected)) as context:
        beta = _organization(context, "Beta Org")
        alpha = _organization(context, "Alpha Org")

        response = _put(context, "anthropic", "only", [beta, alpha])

        expected = {
            "organization_access": "only",
            "organizations": [{"id": str(alpha), "name": "Alpha Org"}, {"id": str(beta), "name": "Beta Org"}],
        }
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), equal_to(expected))
        assert_that(context.client.get(_url("anthropic"), headers=auth(context)).json(), equal_to(expected))
        assert_that(_stored(context, "anthropic"), equal_to(("only", sorted([alpha, beta], key=str))))
        events = _events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            has_entries(
                slug="anthropic",
                previous_organization_access="all",
                organization_access="only",
                added_count=2,
                removed_count=0,
                added_organization_ids=sorted([str(alpha), str(beta)]),
                removed_organization_ids=[],
                organization_ids_truncated=False,
                actor_display=ADMIN_NAME,
                subject_display="Anthropic",
            ),
        )


@pytest.mark.parametrize("access", ["all", "none"])
def test_all_or_none_clears_the_listed_organizations(access):
    with given(_setup(admin, anthropic_connected)) as context:
        alpha = _organization(context, "Alpha Org")
        _put(context, "anthropic", "all_except", [alpha])

        response = _put(context, "anthropic", access, [])

        assert_that(response.json(), equal_to({"organization_access": access, "organizations": []}))
        assert_that(_stored(context, "anthropic"), equal_to((access, [])))
        assert_that(
            _events(context)[-1].payload,
            has_entries(
                previous_organization_access="all_except",
                organization_access=access,
                added_count=0,
                removed_count=1,
                removed_organization_ids=[str(alpha)],
            ),
        )


def test_changing_the_listed_organizations_records_what_was_added_and_removed():
    with given(_setup(admin, anthropic_connected)) as context:
        alpha, beta, gamma = (_organization(context, name) for name in ("Alpha Org", "Beta Org", "Gamma Org"))
        _put(context, "anthropic", "all_except", [alpha, beta])

        _put(context, "anthropic", "all_except", [beta, gamma])

        assert_that(_stored(context, "anthropic"), equal_to(("all_except", sorted([beta, gamma], key=str))))
        assert_that(
            _events(context)[-1].payload,
            has_entries(
                previous_organization_access="all_except",
                organization_access="all_except",
                added_organization_ids=[str(gamma)],
                removed_organization_ids=[str(alpha)],
            ),
        )


def test_a_save_that_changes_nothing_records_no_event():
    with given(_setup(admin, anthropic_connected)) as context:
        alpha = _organization(context, "Alpha Org")
        _put(context, "anthropic", "only", [alpha])

        response = _put(context, "anthropic", "only", [alpha, alpha])

        assert_that(response.status_code, equal_to(200))
        assert_that(_events(context), has_length(1))
        assert_that(_put(context, "openrouter", "all", []).status_code, equal_to(200))
        assert_that(_events(context), has_length(1))


def test_more_than_20_listed_organizations_are_counted_and_the_ids_cut():
    with given(_setup(admin, anthropic_connected)) as context:
        ids = [_organization(context, f"Org {index:02d}") for index in range(21)]

        _put(context, "anthropic", "only", ids)

        payload = _events(context)[0].payload
        assert_that(payload["added_count"], equal_to(21))
        assert_that(payload["added_organization_ids"], equal_to(sorted(str(each) for each in ids)[:20]))
        assert_that(payload["organization_ids_truncated"], equal_to(True))


@pytest.mark.parametrize(
    ("access", "ids", "message"),
    [
        ("all", "known", ORGANIZATIONS_NOT_TAKEN),
        ("none", "known", ORGANIZATIONS_NOT_TAKEN),
        ("only", "unknown", UNKNOWN_ORGANIZATION),
        ("only", "malformed", UNKNOWN_ORGANIZATION),
        ("only", "too_many", TOO_MANY_ORGANIZATIONS),
        ("some", "none", ACCESS_CHOICE),
    ],
)
def test_a_request_that_breaks_a_rule_is_refused_and_stores_nothing(access, ids, message):
    with given(_setup(admin, anthropic_connected)) as context:
        known = _organization(context, "Alpha Org")
        organization_ids = {
            "known": [known],
            "unknown": [known, uuid7()],
            "malformed": ["acme"],
            "too_many": [known] * 1001,
            "none": [],
        }[ids]

        response = _put(context, "anthropic", access, organization_ids)

        assert_that(response.status_code, equal_to(400))
        assert_that(response.json()["detail"], equal_to(message))
        assert_that(_stored(context, "anthropic"), equal_to(("all", [])))
        assert_that(_events(context), has_length(0))


def _uses_its_allowlist(context, organization_id):
    with _session(context) as session:
        organization = session.get(Organization, organization_id)
        assert organization is not None
        organization.allowed_models = [OPENROUTER_MODEL]
        session.add(organization)
        session.commit()


def _uses_its_own_default(context, organization_id):
    with _session(context) as session:
        session.add(OrganizationAgentSettings(organization_id=organization_id, default_model=OPENROUTER_MODEL))
        session.commit()


def _has_a_live_agent(context, organization_id):
    there_is_an_agent(name="Live Agent", organization_id=organization_id)(context)


def _has_a_bot(context, organization_id):
    there_is_an_agent(name="Parent Agent", organization_id=organization_id, deleted=True)(context)
    there_is_an_agent(name="Bot Agent", organization_id=organization_id, parent_agent_id=context.agent.id, bot_slot=1)(
        context
    )


def _has_a_suspended_agent(context, organization_id):
    there_is_an_agent(name="Suspended Agent", organization_id=organization_id)(context)
    with _session(context) as session:
        agent = session.get(Agent, context.agent.id)
        assert agent is not None
        agent.suspend(SuspensionReason.TIER, datetime.now(UTC))
        session.add(agent)
        session.commit()


@pytest.mark.parametrize(
    ("use", "what"),
    [
        (_uses_its_allowlist, "allowed models"),
        (_uses_its_own_default, "its default model"),
        (_has_a_live_agent, "1 Agent"),
        (_has_a_bot, "1 Agent"),
        (_has_a_suspended_agent, "1 Agent"),
    ],
)
def test_withdrawing_openrouter_from_an_organization_that_uses_it_is_refused(use, what):
    with given(_setup(admin)) as context:
        beta = _organization(context, "Beta Org")
        use(context, beta)

        response = _put(context, "openrouter", "all_except", [beta])

        assert_that(response.status_code, equal_to(409))
        assert_that(
            response.json()["detail"], equal_to(f"OpenRouter is still used by Beta Org ({what}). Nothing was saved.")
        )
        assert_that(_stored(context, "openrouter"), equal_to(("all", [])))
        assert_that(_events(context), has_length(0))


def test_an_organization_with_only_deleted_agents_does_not_use_openrouter():
    with given(_setup(admin)) as context:
        beta = _organization(context, "Beta Org")
        there_is_an_agent(name="Retired Agent", organization_id=beta, deleted=True)(context)

        response = _put(context, "openrouter", "all_except", [beta])

        assert_that(response.status_code, equal_to(200))
        assert_that(_stored(context, "openrouter"), equal_to(("all_except", [beta])))


def test_the_refusal_names_what_each_organization_uses_and_at_most_10_of_them():
    with given(_setup(admin)) as context:
        _uses_its_allowlist(context, context.organization.id)
        users = [_organization(context, f"User {index:02d}", [OPENROUTER_MODEL]) for index in range(11)]
        _uses_its_own_default(context, users[0])
        _has_a_live_agent(context, users[0])
        _has_a_live_agent(context, users[0])
        _organization(context, "Idle Org")

        response = _put(context, "openrouter", "none", [])

        named = [
            "Test Organization (allowed models)",
            "User 00 (allowed models, its default model, 2 Agents)",
            *(f"User {index:02d} (allowed models)" for index in range(1, 9)),
        ]
        assert_that(response.status_code, equal_to(409))
        assert_that(
            response.json()["detail"],
            equal_to(f"OpenRouter is still used by {'; '.join(named)} and 2 more organizations. Nothing was saved."),
        )


def test_opening_openrouter_to_more_organizations_is_never_refused():
    with given(_setup(admin)) as context:
        beta = _organization(context, "Beta Org", [OPENROUTER_MODEL])
        with _session(context) as session:
            session.connection().execute(text("UPDATE llm_provider_connection SET organization_access = 'none'"))
            session.commit()

        response = _put(context, "openrouter", "only", [beta])

        assert_that(response.status_code, equal_to(200))


def test_only_withdrawing_from_an_organization_checks_whether_it_uses_openrouter():
    with given(_setup(admin)) as context:
        beta = _organization(context, "Beta Org", [OPENROUTER_MODEL])
        gamma = _organization(context, "Gamma Org")
        _put(context, "openrouter", "all_except", [gamma])

        response = _put(context, "openrouter", "all_except", [])

        assert_that(response.status_code, equal_to(200))
        assert_that(_put(context, "openrouter", "all_except", [beta]).status_code, equal_to(409))


def test_a_connection_other_than_openrouter_is_never_in_use():
    with given(_setup(admin, anthropic_connected)) as context:
        _has_a_live_agent(context, context.organization.id)

        response = _put(context, "anthropic", "none", [])

        assert_that(response.status_code, equal_to(200))


def test_changing_access_leaves_when_the_key_was_saved():
    with given(_setup(admin)) as context:
        saved_at = datetime(2026, 11, 1, tzinfo=UTC)
        with _session(context) as session:
            row = session.get(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
            assert row is not None
            row.api_key_encrypted = encrypt_token("sk-or-v1-stored-key-a1b2", TEST_ENCRYPTION_KEY)
            row.api_key_last4 = "a1b2"
            row.updated_at = saved_at
            session.add(row)
            session.commit()
        gamma = _organization(context, "Gamma Org")

        _put(context, "openrouter", "all_except", [gamma])

        listed = context.client.get(BASE, headers=auth(context)).json()
        assert_that(datetime.fromisoformat(listed[0]["updated_at"]), equal_to(saved_at))


def key_accepted(context):
    check = Mock(return_value=True)
    context.injector.get(LlmProviderKeyChecker).check = check
    context.check = check


def _add(context, access: str | None = None, ids: list | None = None):
    body: dict[str, object] = {"provider_type": "anthropic", "api_key": NEW_KEY}
    if access is not None:
        body["organization_access"] = access
    if ids is not None:
        body["organization_ids"] = [str(organization_id) for organization_id in ids]
    return context.client.post(BASE, json=body, headers=auth(context))


def _created_events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == CREATED_EVENT)).all())


def test_an_added_provider_is_open_to_all_organizations_unless_told_otherwise():
    with given(_setup(admin, key_accepted)) as context:
        response = _add(context)

        assert_that(response.status_code, equal_to(201), response.text)
        assert_that(response.json(), has_entries(organization_access="all", organization_count=0))
        assert_that(_stored(context, "anthropic"), equal_to(("all", [])))
        assert_that((len(_created_events(context)), len(_events(context))), equal_to((1, 0)))


@pytest.mark.parametrize(("access", "listed"), [("none", 0), ("all_except", 1), ("only", 2)])
def test_a_provider_is_added_with_the_access_it_is_given(access, listed):
    with given(_setup(admin, key_accepted)) as context:
        ids = [_organization(context, "Alpha Org"), _organization(context, "Beta Org")][:listed]

        response = _add(context, access, ids)

        assert_that(response.status_code, equal_to(201), response.text)
        assert_that(response.json(), has_entries(organization_access=access, organization_count=listed))
        assert_that(_stored(context, "anthropic"), equal_to((access, sorted(ids, key=str))))
        assert_that(_created_events(context), has_length(1))
        [event] = _events(context)
        assert_that(
            event.payload,
            has_entries(
                slug="anthropic",
                previous_organization_access="all",
                organization_access=access,
                added_count=listed,
                removed_count=0,
                added_organization_ids=sorted(str(each) for each in ids),
                actor_display=ADMIN_NAME,
            ),
        )


@pytest.mark.parametrize(
    ("access", "ids", "message"),
    [
        ("all", "known", ORGANIZATIONS_NOT_TAKEN),
        ("none", "known", ORGANIZATIONS_NOT_TAKEN),
        ("only", "unknown", UNKNOWN_ORGANIZATION),
        ("only", "malformed", UNKNOWN_ORGANIZATION),
        ("only", "too_many", TOO_MANY_ORGANIZATIONS),
        ("some", "none", ACCESS_CHOICE),
    ],
)
def test_an_add_whose_access_breaks_a_rule_is_refused_before_the_key_is_checked(access, ids, message):
    with given(_setup(admin, key_accepted)) as context:
        known = _organization(context, "Alpha Org")
        organization_ids = {
            "known": [known],
            "unknown": [known, uuid7()],
            "malformed": ["acme"],
            "too_many": [known] * 1001,
            "none": [],
        }[ids]

        response = _add(context, access, organization_ids)

        assert_that(response.status_code, equal_to(400))
        assert_that(response.json()["detail"], equal_to(message))
        context.check.assert_not_called()
        with _session(context) as session:
            rows = session.exec(select(LlmProviderConnection).where(LlmProviderConnection.slug == "anthropic")).all()
        assert_that(rows, has_length(0))


def test_deleting_a_connection_removes_its_listed_organizations_and_reviving_it_takes_the_new_access():
    with given(_setup(admin, anthropic_connected, key_accepted)) as context:
        alpha = _organization(context, "Alpha Org")
        beta = _organization(context, "Beta Org")
        _put(context, "anthropic", "only", [alpha])

        deleted = context.client.delete(f"{BASE}/anthropic", headers=auth(context))
        after_delete = _stored(context, "anthropic")[1]
        revived = _add(context, "all_except", [beta])

        assert_that((deleted.status_code, after_delete), equal_to((204, [])))
        assert_that(revived.status_code, equal_to(201), revived.text)
        assert_that(revived.json(), has_entries(organization_access="all_except", organization_count=1))
        assert_that(_stored(context, "anthropic"), equal_to(("all_except", [beta])))
        assert_that(_events(context)[-1].payload, has_entries(added_organization_ids=[str(beta)]))


def test_the_connection_list_shows_each_connections_access_and_how_many_it_lists():
    with given(_setup(admin, anthropic_connected)) as context:
        ids = [_organization(context, "Alpha Org"), _organization(context, "Beta Org")]
        _put(context, "anthropic", "all_except", ids)

        listed = context.client.get(BASE, headers=auth(context)).json()

        assert_that(
            [(each["slug"], each["organization_access"], each["organization_count"]) for each in listed],
            equal_to([("openrouter", "all", 0), ("anthropic", "all_except", 2)]),
        )
