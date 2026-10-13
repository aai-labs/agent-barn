"""Spend LiteLLM missed is still spent (AF-381).

Cost healing finds the price of calls the proxy recorded as free. LiteLLM's team never
counts them, so on credit they would be free credit: an Organization on credit is held to
its credit less what healing found, and its spend and balance read with it. On a renewing
limit nothing changes.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid7

from hamcrest import assert_that, equal_to, has_entries

from api.domains.costs.models import CostRecord
from api.domains.costs.repository import CostRepository
from api.domains.organizations.models import CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_billing import BILLING, _setup, an_owner_on_credit, auth
from api.tests.integration.test_credit_ledger import grant
from api.tests.integration.test_spend_limits import platform_admin, proxy


def calls(context, *rows: tuple[str, bool, int]):
    """(spend, healed, days ago) for each call of the Organization's."""
    now = datetime.now(UTC)
    context.injector.get(CostRepository).upsert_many(
        [
            CostRecord(
                request_id=f"call-{uuid7().hex}",
                litellm_key_hash="agent-key-hash",
                occurred_at=now - timedelta(days=days_ago),
                spend=Decimal(spend),
                model="test",
                status="success",
                organization_id=context.organization.id,
                healed_at=now if healed else None,
            )
            for spend, healed, days_ago in rows
        ]
    )


def test_healed_spend_on_credit_is_kept_off_the_proxy_limit():
    with given(_setup(an_owner_on_credit())) as context:
        calls(context, ("3", True, 0), ("4", False, 0))

        with when("credit is bought"):
            grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")

        with then("the team may spend the credit less the $3 it never counted"):
            proxy(context).apply_team_budget.assert_called_with(
                str(context.organization.id), 27.0, ONE_OFF_BUDGET_WINDOW
            )


def test_healed_spend_on_credit_counts_however_long_ago():
    with given(_setup(an_owner_on_credit())) as context:
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.created_at = datetime.now(UTC) - timedelta(days=500)
        organizations.save(organization)
        calls(context, ("2", True, 400))

        grant(context, CreditGrantKind.PURCHASE, "20", "pi_1")

        proxy(context).apply_team_budget.assert_called_with(str(context.organization.id), 28.0, ONE_OFF_BUDGET_WINDOW)


def test_the_balance_is_net_of_healed_spend():
    with given(_setup(an_owner_on_credit())) as context:
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.llm_spend_usd = 2.5
        organization.llm_spend_observed_at = datetime.now(UTC)
        organizations.save(organization)
        calls(context, ("1.5", True, 0))

        response = context.client.get(BILLING.format(organization_id=context.organization.id), headers=auth(context))

        assert_that(response.json(), has_entries(credit_usd=10.0, spend_usd=4.0, balance_usd=6.0))


def test_a_renewing_limit_is_not_lowered_by_healed_spend():
    with given(platform_admin()) as context:
        calls(context, ("3", True, 0))

        context.client.put(
            f"/api/v1/platform/organizations/{context.organization.id}/llm-budget",
            json={"budget_usd": 50},
            headers=auth(context),
        )

        proxy(context).apply_team_budget.assert_called_with(str(context.organization.id), 50.0, "30d")


def test_healed_memory_on_a_legacy_shared_key_is_not_counted_twice():
    """Those charges are already counted as legacy memory spend, healed or not."""
    with given(_setup(an_owner_on_credit())) as context:
        now = datetime.now(UTC)
        context.injector.get(CostRepository).upsert_many(
            [
                CostRecord(
                    request_id=f"call-{key}",
                    litellm_key_hash=key,
                    occurred_at=now,
                    spend=Decimal(spend),
                    model="test",
                    status="success",
                    is_memory=memory,
                    organization_id=context.organization.id,
                    healed_at=now,
                )
                for key, spend, memory in (("legacy", "5", True), ("team-key", "2", True), ("agent-key", "1", False))
            ]
        )

        healed = context.injector.get(CostRepository).healed_spend(
            context.organization.id, now - timedelta(days=1), exclude_memory_key_hashes=frozenset({"legacy"})
        )

        assert_that(healed, equal_to(Decimal(3)))
