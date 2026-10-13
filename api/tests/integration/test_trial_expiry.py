"""Trial expiry and conversion (AF-381).

A trial whose credit runs out is expired: it stops counting toward the cap on active
trials, keeps its Agents and stays a trial. Buying credit converts a trial into an
ordinary Organization that stays on credit, whether or not it had expired.
"""

from decimal import Decimal

from hamcrest import assert_that, empty, equal_to, has_entries, is_not, none, not_none

from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.organizations.models import CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.domains.organizations.service import OrganizationService
from api.domains.users.repository import UserRepository
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_spend_limits import events_named
from api.tests.integration.test_trial_organizations import _setup, auth, the_organization_is_a_trial

SYSTEM = ActorIdentity(type=ActorIdentityType.SYSTEM, id="test")


def stored(context):
    return context.injector.get(OrganizationRepository).get(context.organization.id)


def expire(context) -> list:
    return context.injector.get(OrganizationRepository).expire_trial_with_event(context.organization.id)


def the_trial_has_its_credit():
    def step(context):
        context.injector.get(OrganizationRepository).record_opening_credit(
            context.organization.id, CreditGrantKind.TRIAL, Decimal(10)
        )

    return step


def test_a_trial_that_runs_out_is_expired_once_and_audited():
    with given(_setup(the_organization_is_a_trial())) as context:
        with when("its credit runs out, and the alert is delivered twice"):
            first = expire(context)
            second = expire(context)

        with then("it is expired, still a trial, and audited once"):
            organization = stored(context)
            assert_that((organization.is_trial, organization.trial_expired_at is not None), equal_to((True, True)))
            assert_that(first, is_not(empty()))
            assert_that(second, equal_to([]))
            assert_that(len(events_named(context, "organization.trial.expired")), equal_to(1))


def test_an_organization_that_is_not_a_trial_does_not_expire():
    with given(_setup()) as context:
        expire(context)
        assert_that(stored(context).trial_expired_at, none())
        assert_that(events_named(context, "organization.trial.expired"), equal_to([]))


def test_an_expired_trial_frees_its_place_under_the_cap():
    with given(_setup(the_organization_is_a_trial())) as context:
        lookup = context.injector.get(OrganizationLookupService)
        before = lookup.count_trials()

        expire(context)

        assert_that((before, lookup.count_trials()), equal_to((1, 0)))


def test_the_organization_read_says_the_trial_has_expired():
    with given(_setup(the_organization_is_a_trial())) as context:
        expire(context)
        response = context.client.get(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))

        assert_that(response.json(), has_entries(is_trial=True, trial_expired_at=not_none()))


def test_buying_credit_converts_an_expired_trial_and_keeps_it_on_credit():
    with given(_setup(the_organization_is_a_trial(), the_trial_has_its_credit())) as context:
        expire(context)

        with when("the trial is converted"):
            converted = context.injector.get(OrganizationService).convert_trial(
                context.organization.id, actor=SYSTEM, actor_display="Credit purchase"
            )

        with then("it is an ordinary Organization, still on its credit, and its creator is free"):
            organization = stored(context)
            assert_that(converted, equal_to(True))
            assert_that(
                (organization.is_trial, organization.trial_expired_at, organization.llm_budget_duration),
                equal_to((False, None, ONE_OFF_BUDGET_WINDOW)),
            )
            assert_that(organization.llm_budget_usd, equal_to(10.0))
            assert_that(context.injector.get(UserRepository).get(context.user.id).trial_ended_at, not_none())
            (event,) = events_named(context, "organization.trial.ended")
            assert_that(event.payload, has_entries(actor_display="Credit purchase"))


def test_converting_an_organization_that_is_not_a_trial_changes_nothing():
    with given(_setup()) as context:
        converted = context.injector.get(OrganizationService).convert_trial(
            context.organization.id, actor=SYSTEM, actor_display="Credit purchase"
        )

        assert_that(converted, equal_to(False))
        assert_that(events_named(context, "organization.trial.ended"), equal_to([]))
