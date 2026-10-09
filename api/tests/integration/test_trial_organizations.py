"""Trial Organizations (AF-368): a self-signed-up user gets one trial Organization with one
Agent, and creates no others, until a Platform Administrator ends the trial."""

import threading
from datetime import UTC, datetime
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_length, not_none
from sqlmodel import Session, select

from api.domains.agents.exceptions import TrialAgentLimitReached
from api.domains.agents.models import Agent, AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.events.catalog import ORGANIZATION_TRIAL_ENDED
from api.domains.events.models import OutboxMessage
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW, LiteLLMClient, LiteLLMError
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

AGENTS = "/api/v1/organizations/{organization_id}/agents"
CREATE = {"name": "Trial Agent", "template_key": "test-template"}


def _setup(*steps):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
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
        event_delivery_tables_are_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_a_template(),
        *steps,
    ]


def the_organization_is_a_trial():
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.is_trial = True
        organization.created_by_user_id = context.user.id
        organization.llm_budget_usd = 10
        organization.llm_budget_duration = ONE_OFF_BUDGET_WINDOW
        organizations.save(organization)

    return step


def the_user_signed_themselves_up():
    def step(context):
        users = context.injector.get(UserRepository)
        user = users.get(context.user.id)
        user.signed_up_at = datetime.now(UTC)
        users.save(user)

    return step


def a_platform_admin_token():
    def step(context):
        context.owner_token = context.access_token
        organization, owner = context.organization, context.user
        del context.organization
        user_id = uuid7()
        # Platform Privilege only: no Membership in the trial.
        there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id)(context)
        context.organization, context.user = organization, owner

    return step


def auth(context, token: str | None = None):
    return {"Authorization": f"Bearer {token or context.access_token}"}


NEW_LIMIT = {"budget_usd": 50, "budget_duration": "30d"}


def _end_trial(context, organization_id=None, body=None):
    return context.client.post(
        f"/api/v1/platform/organizations/{organization_id or context.organization.id}/end-trial",
        json=NEW_LIMIT if body is None else body,
        headers=auth(context),
    )


def the_trial_agent_limit_is(limit: int):
    def step(context):
        context.injector.get(TrialSettingsRepository).set_settings(
            {"agent_limit": limit}, 10, context.user.id, "Platform Admin"
        )

    return step


# --- one Agent per trial -------------------------------------------------------------


def test_a_trial_organization_hires_its_first_agent():
    with given(_setup(the_organization_is_a_trial())) as context:
        with when("the trial's owner hires an Agent"):
            response = context.client.post(AGENTS, json=CREATE, headers=auth(context))

        with then("it is created"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_a_trial_organization_cannot_hire_a_second_agent():
    with given(_setup(the_organization_is_a_trial())) as context:
        context.client.post(AGENTS, json=CREATE, headers=auth(context))

        with when("the trial's owner hires another"):
            response = context.client.post(AGENTS, json={**CREATE, "name": "Second"}, headers=auth(context))

        with then("it is refused, saying why"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("one agent"))


def test_the_trial_agent_limit_is_the_one_platform_administrators_set():
    with given(_setup(the_organization_is_a_trial(), the_trial_agent_limit_is(2))) as context:
        first = context.client.post(AGENTS, json=CREATE, headers=auth(context))
        second = context.client.post(AGENTS, json={**CREATE, "name": "Second"}, headers=auth(context))

        with when("the owner hires a third"):
            third = context.client.post(AGENTS, json={**CREATE, "name": "Third"}, headers=auth(context))

        with then("the first two were hired and the third is refused"):
            assert_that([first.status_code, second.status_code], equal_to([201, 201]))
            assert_that(third.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(third.json()["detail"], contains_string("2 agents"))


def test_two_hires_racing_for_a_trials_last_slot_cannot_both_win():
    """The limit is counted under a lock held until commit, so two concurrent creates
    cannot both see a free slot."""
    with given(_setup(the_organization_is_a_trial())) as context:
        repository = context.injector.get(AgentRepository)
        actor = ActorIdentity(type=ActorIdentityType.USER, id=context.user.id)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def hire(name: str) -> None:
            agent = Agent(
                organization_id=context.organization.id,
                name=name,
                agent_template_id=context.template.id,
                agent_type=AgentType.HERMES,
            )
            barrier.wait()
            try:
                repository.create_with_creator_access(agent, None, actor=actor, agent_limit=1)
                outcomes.append("hired")
            except TrialAgentLimitReached:
                outcomes.append("refused")

        with when("two hires race for the trial's one slot"):
            threads = [threading.Thread(target=hire, args=(name,)) for name in ("First", "Second")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        with then("exactly one is hired"):
            assert_that(sorted(outcomes), equal_to(["hired", "refused"]))
            assert_that(repository.count_active_by_org(context.organization.id), equal_to(1))


def test_an_owner_of_a_trial_who_did_not_sign_up_still_creates_no_organizations():
    """Someone who became a trial's Owner another way (e.g. an ownership transfer) is
    held to the trial's rules while it runs."""
    with given(_setup(the_organization_is_a_trial())) as context:
        response = context.client.post("/api/v1/organizations", json={"name": "Side Org"}, headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_organization_that_is_not_a_trial_hires_as_many_agents_as_it_likes():
    with given(_setup()) as context:
        context.client.post(AGENTS, json=CREATE, headers=auth(context))

        response = context.client.post(AGENTS, json={**CREATE, "name": "Second"}, headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_the_organization_read_says_whether_it_is_a_trial():
    with given(_setup(the_organization_is_a_trial())) as context:
        response = context.client.get(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))

        assert_that(response.json(), has_entries(is_trial=True, trial_agent_limit=1))


# --- no further Organizations for self-signed-up users -----------------------------------


def test_a_self_signed_up_user_cannot_create_another_organization():
    with given(_setup(the_organization_is_a_trial(), the_user_signed_themselves_up())) as context:
        with when("they try to create an Organization"):
            response = context.client.post("/api/v1/organizations", json={"name": "Second Org"}, headers=auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_deleting_the_trial_does_not_let_its_owner_create_organizations():
    with given(_setup(the_organization_is_a_trial(), the_user_signed_themselves_up())) as context:
        deleted = context.client.delete(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))
        assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT), deleted.text)

        with when("they try to create an ordinary Organization instead"):
            response = context.client.post("/api/v1/organizations", json={"name": "Fresh Org"}, headers=auth(context))

        with then("it is refused: only ending the trial lifts the block"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_self_signed_up_user_creates_organizations_once_their_trial_has_ended():
    with given(
        _setup(the_organization_is_a_trial(), the_user_signed_themselves_up(), a_platform_admin_token())
    ) as context:
        _end_trial(context)

        with when("the former trial's owner creates an Organization"):
            response = context.client.post(
                "/api/v1/organizations", json={"name": "Second Org"}, headers=auth(context, context.owner_token)
            )

        with then("it is created"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_a_user_brought_in_by_an_administrator_still_creates_organizations():
    with given(_setup()) as context:
        response = context.client.post("/api/v1/organizations", json={"name": "Second Org"}, headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


# --- ending a trial ---------------------------------------------------------------------


def test_a_platform_administrator_ends_a_trial():
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        with when("they end the trial"):
            response = _end_trial(context)

        with then("the Organization is no longer a trial, on the spend limit they chose"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(is_trial=False, llm_budget_usd=50.0, llm_budget_duration="30d"))
            assert_that(
                context.injector.get(OrganizationRepository).get(context.organization.id).is_trial, equal_to(False)
            )

        with then("the change is audited"):
            assert_that(_trial_ended_events(context), has_length(1))

        with then("its owner is recorded as past their trial"):
            owner = context.injector.get(UserRepository).get(context.user.id)
            assert_that(owner.trial_ended_at, not_none())


def test_an_ended_trial_hires_more_agents():
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        owner = context.owner_token
        context.client.post(AGENTS, json=CREATE, headers=auth(context, owner))
        _end_trial(context)

        with when("the owner hires a second Agent"):
            response = context.client.post(AGENTS, json={**CREATE, "name": "Second"}, headers=auth(context, owner))

        with then("it is created"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_ending_a_trial_twice_is_refused_the_second_time():
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        _end_trial(context)

        response = _end_trial(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_trial_ended_events(context), has_length(1))


def test_ending_a_trial_that_already_ended_changes_nothing_at_all():
    with given(_setup(a_platform_admin_token())) as context:
        before = context.injector.get(OrganizationRepository).get(context.organization.id)

        with when("an administrator ends the trial of an Organization that is not one"):
            response = _end_trial(context)

        with then("it is refused, and its spend limit is left alone"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            after = context.injector.get(OrganizationRepository).get(context.organization.id)
            assert_that(
                (after.llm_budget_usd, after.llm_budget_duration),
                equal_to((before.llm_budget_usd, before.llm_budget_duration)),
            )


def test_a_trial_still_ends_when_its_new_limit_cannot_be_applied_yet():
    """The proxy failing must not leave a trial on a renewing budget: everything is
    saved, the trial ends, and the reconciler applies the limit later."""
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        context.injector.get(LiteLLMClient).apply_team_budget.side_effect = LiteLLMError("proxy down")

        with when("the administrator ends the trial while the proxy is down"):
            response = _end_trial(context)

        with then("they are told it isn't applied yet, but the trial has ended on the new limit"):
            assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
            organization = context.injector.get(OrganizationRepository).get(context.organization.id)
            assert_that(
                (organization.is_trial, organization.llm_budget_usd, organization.llm_budget_duration),
                equal_to((False, 50.0, "30d")),
            )


def test_ending_a_trial_needs_a_spend_limit():
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        response = _end_trial(context, body={})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        assert_that(context.injector.get(OrganizationRepository).get(context.organization.id).is_trial, equal_to(True))


def test_ending_the_trial_of_an_unknown_organization_is_not_found():
    with given(_setup(a_platform_admin_token())) as context:
        response = _end_trial(context, organization_id=uuid7())

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_organization_owner_cannot_end_their_own_trial():
    with given(_setup(the_organization_is_a_trial())) as context:
        response = _end_trial(context)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_raising_a_trials_credit_keeps_it_one_off():
    with given(_setup(the_organization_is_a_trial(), a_platform_admin_token())) as context:
        with when("a Platform Administrator raises the amount without choosing a window"):
            response = context.client.put(
                f"/api/v1/platform/organizations/{context.organization.id}/llm-budget",
                json={"budget_usd": 25},
                headers=auth(context),
            )

        with then("the trial gets the new amount, still granted once"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(llm_budget_usd=25.0, llm_budget_duration=ONE_OFF_BUDGET_WINDOW))


def _trial_ended_events(context) -> list[OutboxMessage]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(session.exec(select(OutboxMessage).where(OutboxMessage.event_name == ORGANIZATION_TRIAL_ENDED)))
