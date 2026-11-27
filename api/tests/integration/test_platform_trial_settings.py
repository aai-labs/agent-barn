"""Trial settings (AF-368): Platform Administrators set the credit a new trial
Organization starts with, how many Agents a trial runs and how many trials may be active
at once, and every change is audited. A trial is an Organization on the Free Tier, so its
credit and Agent limit are stored on the Free row (Tiers, PR 4)."""

from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length, none, not_none
from sqlmodel import Session, col, select

from api.domains.events.catalog import PLATFORM_TIER_CHANGED, PLATFORM_TRIAL_SETTINGS_CHANGED
from api.domains.events.models import OutboxMessage
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.onboarding import the_tier_is_offered
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/trial"


def _setup(*steps, telegram: bool = True, payments: bool = False):
    return [
        set_env_variable(
            {
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token" if telegram else "",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot" if telegram else "",
                "TIERS_MOCK_PAYMENTS": str(payments).lower(),
            }
        ),
        prepare_injector(),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        *steps,
    ]


def a_platform_admin():
    def step(context):
        user_id = uuid7()
        there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id)(context)

    return step


def trial_organizations(count: int, ended: int = 0):
    def step(context):
        repository = context.injector.get(OrganizationRepository)
        for index in range(count + ended):
            repository.save(Organization(name=f"Trial {index}", allowed_models=["*"], is_trial=index < count))

    return step


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _events(context, event_name: str) -> list[OutboxMessage]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(
                select(OutboxMessage)
                .where(OutboxMessage.event_name == event_name)
                .order_by(col(OutboxMessage.created_at))
            )
        )


def _trial_setting_events(context) -> list[OutboxMessage]:
    return _events(context, PLATFORM_TRIAL_SETTINGS_CHANGED)


def _free_tier_events(context) -> list[OutboxMessage]:
    """The trial's credit and Agent limit are the Free Tier's, audited as its changes."""
    return _events(context, PLATFORM_TIER_CHANGED)


def test_signup_is_closed_until_an_administrator_configures_it():
    with given(_setup(a_platform_admin())) as context:
        with when("a Platform Administrator reads the trial settings"):
            response = context.client.get(BASE, headers=auth(context))

        with then("signup is off, with the Free Tier's seeded credit and limit, never saved"):
            assert_that(response.status_code, equal_to(200))
            assert_that(
                response.json(),
                has_entries(
                    self_signup_enabled=False,
                    credit_usd=10.0,
                    agent_limit=1,
                    free_tier_offered=False,
                    signup_tier_available=False,
                    max_active_trials=none(),
                    updated_at=none(),
                ),
            )


def test_a_platform_administrator_sets_the_trial_credit():
    with given(_setup(a_platform_admin())) as context:
        with when("they set the credit"):
            saved = context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with then("it is stored and read back"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(credit_usd=25.0, updated_at=not_none()))
            read = context.client.get(BASE, headers=auth(context))
            assert_that(read.json(), has_entries(credit_usd=25.0))

        with then("the change is audited as the Free Tier's, with its before and after values"):
            events = _free_tier_events(context)
            assert_that(events, has_length(1))
            assert_that(events[0].payload, has_entries(setting="one_time_credit_usd", previous=10.0, current=25.0))


def test_the_trial_credit_and_agent_limit_are_the_free_tiers():
    with given(_setup(a_platform_admin())) as context:
        with when("they set the credit and the agent limit"):
            context.client.put(BASE, headers=auth(context), json={"credit_usd": 25, "agent_limit": 2})

        with then("the Free Tier grants them"):
            free = next(
                tier
                for tier in context.client.get("/api/v1/platform/tiers", headers=auth(context)).json()
                if tier["key"] == "free"
            )
            assert_that(free, has_entries(one_time_credit_usd="25.00", agent_limit=2))


def test_saving_the_same_credit_again_records_nothing_new():
    with given(_setup(a_platform_admin())) as context:
        context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with when("the same credit is saved again"):
            response = context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with then("no second change is audited"):
            assert_that(response.status_code, equal_to(200))
            assert_that(_free_tier_events(context), has_length(1))


def test_a_platform_administrator_sets_the_trial_agent_limit():
    with given(_setup(a_platform_admin())) as context:
        context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with when("they change only the agent limit"):
            saved = context.client.put(BASE, headers=auth(context), json={"agent_limit": 3})

        with then("it is stored, and the credit is left as it was"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(credit_usd=25.0, agent_limit=3))

        with then("each change is audited on its own"):
            events = _free_tier_events(context)
            assert_that(events, has_length(2))
            assert_that(events[1].payload, has_entries(setting="agent_limit", previous=1, current=3))


def test_a_platform_administrator_caps_the_active_trials():
    with given(_setup(a_platform_admin())) as context:
        with when("they cap the trials that may be active at once"):
            saved = context.client.put(BASE, headers=auth(context), json={"max_active_trials": 20})

        with then("it is stored, and the other settings are left as they were"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(credit_usd=10.0, agent_limit=1, max_active_trials=20))

        with then("the change is audited, from no cap to the cap"):
            events = _trial_setting_events(context)
            assert_that(events, has_length(1))
            assert_that(events[0].payload, has_entries(setting="max_active_trials", previous=none(), current=20.0))


def test_a_platform_administrator_removes_the_cap():
    with given(_setup(a_platform_admin())) as context:
        context.client.put(BASE, headers=auth(context), json={"max_active_trials": 20})

        with when("they clear the cap"):
            saved = context.client.put(BASE, headers=auth(context), json={"max_active_trials": None})

        with then("trials are uncapped again, and the change is audited"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(max_active_trials=none()))
            events = _trial_setting_events(context)
            assert_that(events, has_length(2))
            assert_that(events[1].payload, has_entries(previous=20.0, current=none()))


def test_the_settings_say_how_many_trials_are_active():
    with given(_setup(a_platform_admin(), trial_organizations(2, ended=1))) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.json(), has_entries(active_trials=2))


@pytest.mark.parametrize("cap", [0, -1, 1.5, 100_001])
def test_an_invalid_trial_cap_is_refused(cap):
    with given(_setup(a_platform_admin())) as context:
        response = context.client.put(BASE, headers=auth(context), json={"max_active_trials": cap})

        assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("setting", ["self_signup_enabled", "credit_usd", "agent_limit"])
def test_the_credit_and_agent_limit_cannot_be_cleared(setting):
    with given(_setup(a_platform_admin())) as context:
        response = context.client.put(BASE, headers=auth(context), json={setting: None})

        assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("limit", [0, 51, 1.5])
def test_an_invalid_agent_limit_is_refused(limit):
    with given(_setup(a_platform_admin())) as context:
        response = context.client.put(BASE, headers=auth(context), json={"agent_limit": limit})

        assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("credit", [-1, 10_001, "lots"])
def test_an_invalid_credit_is_refused(credit):
    with given(_setup(a_platform_admin())) as context:
        with when("an out-of-range or non-numeric credit is saved"):
            response = context.client.put(BASE, headers=auth(context), json={"credit_usd": credit})

        with then("it is refused"):
            assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("method,payload", [("GET", None), ("PUT", {"self_signup_enabled": True, "credit_usd": 5})])
def test_an_organization_owner_cannot_manage_trial_settings(method, payload):
    with given(_setup(there_is_an_organization_with_user_and_access_token())) as context:
        with when("an Organization Owner without Platform Privilege tries"):
            response = context.client.request(method, BASE, headers=auth(context), json=payload)

        with then("they are refused"):
            assert_that(response.status_code, equal_to(403))


def test_an_unauthenticated_caller_cannot_read_trial_settings():
    with given(_setup()) as context:
        response = context.client.get(BASE)
        assert_that(response.status_code, equal_to(401))


def test_signup_can_be_enabled_together_with_positive_credit_and_is_audited():
    with given(_setup(a_platform_admin(), the_tier_is_offered())) as context:
        response = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True, "credit_usd": 20})
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(self_signup_enabled=True, credit_usd=20)
        )
        events = {event.payload["setting"]: event.payload for event in _trial_setting_events(context)}
        assert_that(events["self_signup_enabled"], has_entries(previous=False, current=True))
        assert_that(type(events["self_signup_enabled"]["current"]), equal_to(bool))
        (credit,) = _free_tier_events(context)
        assert_that(credit.payload, has_entries(setting="one_time_credit_usd", previous=10, current=20))


def test_signup_cannot_be_enabled_without_positive_credit():
    with given(_setup(a_platform_admin(), the_tier_is_offered())) as context:
        context.client.put(BASE, headers=auth(context), json={"credit_usd": 0})
        response = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True})
        assert_that(response.status_code, equal_to(400))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(self_signup_enabled=False, credit_usd=0)
        )
        assert_that(_trial_setting_events(context), has_length(0))
        assert_that(_free_tier_events(context), has_length(1))


def test_credit_cannot_be_zeroed_while_signup_is_enabled():
    with given(_setup(a_platform_admin(), the_tier_is_offered())) as context:
        context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True, "credit_usd": 20})
        response = context.client.put(BASE, headers=auth(context), json={"credit_usd": 0})
        assert_that(response.status_code, equal_to(400))
        assert_that(
            context.client.get(BASE, headers=auth(context)).json(), has_entries(self_signup_enabled=True, credit_usd=20)
        )
        assert_that(_trial_setting_events(context), has_length(1))
        assert_that(_free_tier_events(context), has_length(1))


def test_disabling_signup_allows_zero_credit_in_the_same_save():
    with given(_setup(a_platform_admin(), the_tier_is_offered())) as context:
        context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True, "credit_usd": 20})
        response = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": False, "credit_usd": 0})
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), has_entries(self_signup_enabled=False, credit_usd=0))


def test_signup_cannot_be_enabled_while_no_tier_is_offered():
    with given(_setup(a_platform_admin())) as context:
        with when("a Platform Administrator enables signup with every Tier withdrawn"):
            response = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True})

        with then("it is refused and nothing changes"):
            assert_that(response.status_code, equal_to(400))
            assert_that(
                response.json()["detail"],
                equal_to(
                    "Offer Free with Agent Barn Telegram configured, or a purchasable paid tier, before enabling self-signup."
                ),
            )
            assert_that(
                context.client.get(BASE, headers=auth(context)).json(),
                has_entries(self_signup_enabled=False, signup_tier_available=False),
            )
            assert_that(_trial_setting_events(context), has_length(0))


@pytest.mark.parametrize(
    "key,telegram,payments,expected",
    [
        ("free", True, False, 200),
        ("cloud_1", False, True, 200),
        ("pilot", True, True, 400),
        ("cloud_1", True, False, 400),
        ("free", False, True, 400),
    ],
)
def test_signup_can_be_enabled_only_with_a_usable_tier(key, telegram, payments, expected):
    with given(_setup(a_platform_admin(), the_tier_is_offered(key), telegram=telegram, payments=payments)) as context:
        response = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True})

        assert_that(response.status_code, equal_to(expected), response.text)
        available = expected == 200
        settings = context.client.get(BASE, headers=auth(context))
        assert_that(settings.json(), has_entries(self_signup_enabled=available, signup_tier_available=available))


def test_signup_already_enabled_stays_editable_after_the_last_tier_is_withdrawn():
    with given(_setup(a_platform_admin(), the_tier_is_offered())) as context:
        context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True})
        the_tier_is_offered(offered=False)(context)

        with when("a Platform Administrator saves the settings as the page sends them"):
            response = context.client.put(
                BASE, headers=auth(context), json={"self_signup_enabled": True, "max_active_trials": 5}
            )

        with then("the save goes through, and the read says no Tier is offered"):
            assert_that(response.status_code, equal_to(200), response.text)
            assert_that(
                response.json(), has_entries(self_signup_enabled=True, max_active_trials=5, signup_tier_available=False)
            )


@pytest.mark.parametrize("offered_key", [None, "cloud_1"])
def test_signup_rechecks_the_transition_and_catalog_at_write_time(monkeypatch, offered_key):
    key = offered_key or "free"
    with given(_setup(a_platform_admin(), the_tier_is_offered(key), payments=True)) as context:
        repository = context.injector.get(TrialSettingsRepository)
        if offered_key is None:
            opened = context.client.put(BASE, headers=auth(context), json={"self_signup_enabled": True})
            assert_that(opened.status_code, equal_to(200), opened.text)
            the_tier_is_offered(offered=False)(context)
        write = repository.set_settings

        def interleave_before_write(*args, **kwargs):
            if offered_key is None:
                write({"self_signup_enabled": False}, context.user.id, "Platform Admin")
            else:
                the_tier_is_offered(offered_key, offered=False)(context)
            return write(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(repository, "set_settings", interleave_before_write)
            stale_save = context.client.put(
                BASE, headers=auth(context), json={"self_signup_enabled": True, "max_active_trials": 5}
            )
        assert_that(stale_save.status_code, equal_to(400), stale_save.text)
        settings = context.client.get(BASE, headers=auth(context))
        assert_that(
            settings.json(),
            has_entries(self_signup_enabled=False, max_active_trials=none(), signup_tier_available=False),
        )


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_unauthenticated_callers_cannot_change_signup_policy(method):
    with given(_setup()) as context:
        response = context.client.request(
            method, BASE, json={"self_signup_enabled": True, "credit_usd": 20} if method == "PUT" else None
        )
        assert_that(response.status_code, equal_to(401))
