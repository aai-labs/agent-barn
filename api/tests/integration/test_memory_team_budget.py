"""Organization credentials and accounting at the API/database boundary."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

from hamcrest import assert_that, equal_to, has_length
from sqlalchemy import text
from sqlmodel import Session, select
from starlette.testclient import TestClient

from api.core.config import Config
from api.domains.agent_memory.models import OrganizationMemoryKey
from api.domains.costs.models import CostRecord
from api.domains.costs.repository import CostRepository
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.memory_runtime_app import create_memory_runtime_app
from api.tests.core.givenpy import given
from api.tests.steps.agent_memory import agent_memory_api_setup
from api.tests.steps.cost import memory_budget_is_present

URL = "/memory/runtime/v1/model"
SERVICE_KEY = "memory-team-contract-service-key"


def setup(context):
    context.injector.get(Config).memory_runtime_service_key = SERVICE_KEY


def request(context, bank=None, token=SERVICE_KEY):
    return TestClient(create_memory_runtime_app(context.injector)).get(
        URL, params={"bank": bank} if bank else {}, headers={"Authorization": f"Bearer {token}"}
    )


def test_bank_credentials_are_encrypted_reused_and_never_returned_to_agents(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        litellm = context.injector.get(LiteLLMClient)
        key = "sk-memory-team-contract"
        monkeypatch.setattr(litellm, "generate_memory_key", Mock(return_value=key))
        monkeypatch.setattr(litellm, "_key_info", Mock(return_value={"team_id": str(context.organization.id)}))
        bank = f"org-{context.organization.id}"
        assert_that(request(context, bank, token="agent-test-key").status_code, equal_to(401))
        first = request(context, bank)
        assert_that(first.status_code, equal_to(200), first.text)
        assert_that(first.json()["api_key"], equal_to(key))
        assert_that(request(context, bank).json(), equal_to(first.json()))
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            rows = session.exec(select(OrganizationMemoryKey)).all()
        assert_that(rows, has_length(1))
        assert_that(rows[0].organization_id, equal_to(context.organization.id))
        assert_that(key in rows[0].model_dump_json(), equal_to(False))
        assert_that(rows[0].key_hash, equal_to(hashlib.sha256(key.encode()).hexdigest()))
        assert_that(litellm.generate_memory_key.call_count, equal_to(1))
        assert_that(request(context, "org-forged").status_code, equal_to(422))
        assert_that(request(context, "org-11111111-2222-3333-4444-555555555555").status_code, equal_to(404))


def test_legacy_memory_reduces_team_allowance_and_counts_in_alerts_without_double_counting():
    with given(agent_memory_api_setup(setup, memory_budget_is_present(limit=100, runtime_spend=30))) as context:
        config = context.injector.get(Config)
        legacy_hash = next(iter(config.memory_cost_key_hashes))
        context.injector.get(CostRepository).upsert_many(
            [
                CostRecord(
                    request_id=f"team-{kind}",
                    litellm_key_hash=key,
                    occurred_at=datetime.now(UTC),
                    spend=Decimal(amount),
                    model="test",
                    status="success",
                    is_memory=True,
                    organization_id=context.organization.id,
                )
                for kind, key, amount in [("legacy", legacy_hash, "40"), ("current", "team-key-hash", "20")]
            ]
        )
        budgets = context.injector.get(OrganizationLlmBudgetService)
        org = budgets.organization_repository.get(context.organization.id)
        budgets.ensure_memory_team(org)
        assert_that(budgets.litellm.apply_team_budget.call_args.args[1], equal_to(60))
        budgets.litellm.get_team_budget_status.return_value = {
            "spend": 45,
            "renews_at": org.llm_budget_renews_at.isoformat(),
        }
        crossings = budgets._check_one_budget(org)
        assert_that(crossings[0].spend_usd, equal_to(85))
        assert_that(crossings[0].threshold_percent, equal_to(80))
        # Persisted team spend already includes the current team key's $20.
        assert_that(budgets.organization_repository.get(org.id).llm_spend_usd, equal_to(45))
        response = context.client.get(
            "/api/v1/organizations/{organization_id}/llm-budget",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json()["spend_usd"], equal_to(85))


def test_memory_window_has_a_partial_index_and_legacy_hash_filter():
    with given(agent_memory_api_setup(setup)) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with delegate.engine.connect() as connection:
            index = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_cost_record_memory_org_occurred'")
            ).scalar_one()
        assert_that("(organization_id, occurred_at)" in index, equal_to(True))
        assert_that("WHERE (is_memory IS TRUE)" in index, equal_to(True))


def test_public_product_api_does_not_expose_processing_credentials():
    with given(agent_memory_api_setup(setup)) as context:
        assert_that(context.client.get("/api/v1/health").status_code, equal_to(200))
        assert_that(
            context.client.get(
                "/api/v1/memory/runtime/v1/model", headers={"Authorization": f"Bearer {SERVICE_KEY}"}
            ).status_code,
            equal_to(404),
        )
