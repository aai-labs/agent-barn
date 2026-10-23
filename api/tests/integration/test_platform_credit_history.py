"""Every Organization's credit history, for Platform Administrators (AF-381).

The platform's view of what was bought, refunded, charged back or adjusted across all
Organizations, newest first: a page at a time, narrowed to one kind or one Organization.
"""

from decimal import Decimal

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries

from api.domains.organizations.models import CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_billing import _setup, a_platform_administrator, an_owner_on_credit, auth
from api.tests.integration.test_credit_ledger import grant
from api.tests.integration.test_credit_spend_limits import the_organization_runs_on_credit
from api.tests.steps.organization import there_is_an_organization

HISTORY = "/api/v1/platform/billing/credit-history"


def two_organizations_with_credit():
    """Jane's Organization (trial, then a $20 purchase) and Acme (trial only)."""

    def step(context):
        an_owner_on_credit()(context)
        grant(context, CreditGrantKind.PURCHASE, "20", "pi_jane", amount_paid_usd=Decimal("21.10"))
        context.janes = context.organization.id
        there_is_an_organization(name="Acme")(context)
        the_organization_runs_on_credit()(context)
        context.injector.get(OrganizationRepository).record_opening_credit(
            context.organization.id, CreditGrantKind.TRIAL, Decimal(10)
        )
        context.acme = context.organization.id

    return step


def history(context, **params):
    return context.client.get(HISTORY, params=params, headers=auth(context))


def test_a_platform_administrator_sees_every_organizations_credit_newest_first():
    with given(_setup(two_organizations_with_credit(), a_platform_administrator())) as context:
        with when("the history is read"):
            response = history(context)

        with then("every change to every Organization's credit is listed, newest first"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(body, has_entries(page=1, total=3))
            assert_that(
                [(item["organization_name"], item["kind"]) for item in body["items"]],
                contains_exactly(
                    ("Acme", "trial"), ("Jane's Organization", "purchase"), ("Jane's Organization", "trial")
                ),
            )
            assert_that(
                body["items"][1],
                has_entries(
                    organization_id=str(context.janes),
                    credit_usd=20.0,
                    amount_paid_usd=21.1,
                    by="Test",
                    reference="pi_jane",
                ),
            )


def test_the_history_narrows_to_one_kind():
    with given(_setup(two_organizations_with_credit(), a_platform_administrator())) as context:
        body = history(context, kind="purchase").json()

        assert_that(body["total"], equal_to(1))
        assert_that(body["items"][0], has_entries(kind="purchase", reference="pi_jane"))


def test_the_history_narrows_to_one_organization():
    with given(_setup(two_organizations_with_credit(), a_platform_administrator())) as context:
        body = history(context, organization_id=str(context.acme)).json()

        assert_that([item["organization_name"] for item in body["items"]], contains_exactly("Acme"))


def test_the_history_is_read_a_page_at_a_time():
    with given(_setup(two_organizations_with_credit(), a_platform_administrator())) as context:
        body = history(context, page=2, page_size=2).json()

        assert_that(body, has_entries(page=2, page_size=2, total=3))
        assert_that([item["kind"] for item in body["items"]], contains_exactly("trial"))


def test_only_a_platform_administrator_reads_it():
    with given(_setup(an_owner_on_credit())) as context:
        assert_that(history(context).status_code, equal_to(status.HTTP_403_FORBIDDEN))
