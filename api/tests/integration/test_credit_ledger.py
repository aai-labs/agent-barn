"""The credit ledger (AF-381).

An Organization on credit has a record of every change to its credit — the trial's,
each purchase, refunds, chargebacks and platform adjustments — and its spend ceiling
is their sum. The balance is that ceiling less everything spent, so it can go below
zero (a chargeback after the credit was spent) and the next grant pays that off first.
"""

from decimal import Decimal
from uuid import uuid7

import pytest
from fastapi import HTTPException, status
from hamcrest import assert_that, equal_to, has_entries

from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.organizations.exceptions import OrganizationNotOnCredit
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.models import CreditGrantCreate, CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_credit_spend_limits import CREDIT, the_organization_runs_on_credit
from api.tests.integration.test_spend_limits import (
    PLATFORM_BUDGET,
    auth,
    events_named,
    platform_admin,
    proxy,
    stored_organization,
)

SYSTEM = ActorIdentity(type=ActorIdentityType.SYSTEM, id="test")


def the_organization_has_its_trial_credit():
    """An Organization on credit as signup leaves it: its trial credit is its first grant."""

    def step(context):
        the_organization_runs_on_credit()(context)
        context.injector.get(OrganizationRepository).record_opening_credit(
            context.organization.id, CreditGrantKind.TRIAL, Decimal(str(CREDIT))
        )

    return step


def on_credit() -> list:
    return [*platform_admin(), the_organization_has_its_trial_credit()]


def grant(context, kind: CreditGrantKind, credit_usd: str, external_ref: str | None = None, **fields) -> bool:
    return context.injector.get(OrganizationLlmBudgetService).grant_credit(
        context.organization.id,
        CreditGrantCreate(kind=kind, credit_usd=Decimal(credit_usd), external_ref=external_ref, **fields),
        actor=SYSTEM,
        actor_display="Test",
    )


def ledger(context) -> list[tuple[CreditGrantKind, Decimal]]:
    grants = context.injector.get(OrganizationRepository).list_credit_grants(context.organization.id)
    return [(g.kind, g.credit_usd) for g in grants]


def test_a_purchase_raises_the_ceiling_and_reaches_the_proxy():
    with given(on_credit()) as context:
        with when("credit is bought"):
            applied = grant(context, CreditGrantKind.PURCHASE, "20", "pi_1", amount_paid_usd=Decimal(20))

        with then("the ceiling is everything granted, on the row and on the team"):
            assert_that(applied, equal_to(True))
            organization = stored_organization(context)
            assert_that(
                (organization.llm_budget_usd, organization.llm_budget_duration),
                equal_to((CREDIT + 20, ONE_OFF_BUDGET_WINDOW)),
            )
            proxy(context).apply_team_budget.assert_called_with(
                str(context.organization.id), CREDIT + 20, ONE_OFF_BUDGET_WINDOW
            )

        with then("the grant is recorded and audited"):
            assert_that(
                ledger(context),
                equal_to([(CreditGrantKind.TRIAL, Decimal(10)), (CreditGrantKind.PURCHASE, Decimal(20))]),
            )
            (event,) = events_named(context, "organization.llm_budget.changed")
            assert_that(event.payload, has_entries(ceiling_usd=CREDIT + 20, previous_ceiling_usd=CREDIT))


def test_the_same_payment_is_granted_once():
    with given(on_credit()) as context:
        grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")

        with when("the same payment is reported again"):
            applied = grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")

        with then("nothing more is granted"):
            assert_that(applied, equal_to(False))
            assert_that(stored_organization(context).llm_budget_usd, equal_to(CREDIT + 20))
            assert_that(len(ledger(context)), equal_to(2))


def test_a_refund_takes_its_credit_back_off():
    with given(on_credit()) as context:
        grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")
        grant(context, CreditGrantKind.REFUND, "-20", "re_1")
        assert_that(stored_organization(context).llm_budget_usd, equal_to(CREDIT))


def test_the_ceiling_never_goes_below_zero():
    """The ceiling can't be negative; the balance can, since spend is counted against it."""
    with given(on_credit()) as context:
        grant(context, CreditGrantKind.CHARGEBACK, "-25", "dp_1")
        assert_that(stored_organization(context).llm_budget_usd, equal_to(0.0))


def test_a_grant_clears_an_own_limit_left_from_before_credit():
    """An own limit is not in force on credit, and must not block a ceiling that falls
    below it."""
    with given([*platform_admin(), the_organization_runs_on_credit(own_limit_usd=8.0)]) as context:
        context.injector.get(OrganizationRepository).record_opening_credit(
            context.organization.id, CreditGrantKind.TRIAL, Decimal(str(CREDIT))
        )
        grant(context, CreditGrantKind.REFUND, "-5", "re_1")

        organization = stored_organization(context)
        assert_that((organization.llm_budget_usd, organization.llm_own_budget_usd), equal_to((5.0, None)))


def test_an_organization_not_on_credit_is_granted_nothing():
    with given(platform_admin()) as context:
        with pytest.raises(OrganizationNotOnCredit):
            grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")
        assert_that(ledger(context), equal_to([]))


@pytest.mark.parametrize("credit_usd", ["0", "-5"])
def test_a_purchase_must_add_credit(credit_usd):
    with pytest.raises(ValueError):
        CreditGrantCreate(kind=CreditGrantKind.PURCHASE, credit_usd=Decimal(credit_usd))


@pytest.mark.parametrize("kind", [CreditGrantKind.REFUND, CreditGrantKind.CHARGEBACK])
def test_a_refund_or_chargeback_must_take_credit_off(kind):
    with pytest.raises(ValueError):
        CreditGrantCreate(kind=kind, credit_usd=Decimal(5))


def test_a_platform_change_to_the_ceiling_on_credit_is_recorded_as_an_adjustment():
    with given(on_credit()) as context:
        with when("a platform administrator sets the ceiling directly"):
            response = context.client.put(
                PLATFORM_BUDGET.format(organization_id=context.organization.id),
                json={"budget_usd": 25},
                headers=auth(context),
            )

        with then("the difference is recorded, so the ledger still adds up to the ceiling"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                ledger(context),
                equal_to([(CreditGrantKind.TRIAL, Decimal(10)), (CreditGrantKind.ADJUSTMENT, Decimal(15))]),
            )
            assert_that(stored_organization(context).llm_budget_usd, equal_to(25.0))


def test_a_platform_change_to_a_renewing_ceiling_records_nothing():
    with given(platform_admin()) as context:
        context.client.put(
            PLATFORM_BUDGET.format(organization_id=context.organization.id),
            json={"budget_usd": 25},
            headers=auth(context),
        )
        assert_that(ledger(context), equal_to([]))


def test_a_grant_stands_when_the_proxy_cannot_be_written():
    """A payment is never refused for the proxy's sake: the reconciler applies the ledger."""
    with given(on_credit()) as context:
        proxy(context).apply_team_budget.side_effect = RuntimeError("proxy down")

        applied = grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")

        assert_that(applied, equal_to(True))
        assert_that(stored_organization(context).llm_budget_usd, equal_to(CREDIT + 20))


def test_credit_for_an_unknown_organization_is_not_found():
    with given(on_credit()) as context:
        with pytest.raises(HTTPException) as refused:
            context.injector.get(OrganizationLlmBudgetService).grant_credit(
                uuid7(),
                CreditGrantCreate(kind=CreditGrantKind.PURCHASE, credit_usd=Decimal(5)),
                actor=SYSTEM,
                actor_display="Test",
            )
        assert_that(refused.value.status_code, equal_to(status.HTTP_404_NOT_FOUND))
