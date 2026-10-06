import hashlib
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from hamcrest import assert_that, equal_to
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agent_memory.models import MemoryKeyRevocation, OrganizationMemoryKey
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMKeyNotFound
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.integration.test_memory_team_budget import request, setup
from api.tests.steps.agent_memory import agent_memory_api_setup


def provision(context, monkeypatch):
    client = context.injector.get(LiteLLMClient)
    monkeypatch.setattr(client, "generate_memory_key", Mock(side_effect=["sk-first", "sk-second"]))
    monkeypatch.setattr(
        client, "_key_info", Mock(return_value={"team_id": str(context.organization.id), "blocked": False})
    )
    bank = f"org-{context.organization.id}"
    assert_that(request(context, bank).json()["api_key"], equal_to("sk-first"))
    return client, bank


def test_missing_memory_key_is_replaced_but_a_blocked_key_is_not(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client, bank = provision(context, monkeypatch)
        client._key_info.side_effect = LiteLLMKeyNotFound("missing")
        assert_that(request(context, bank).json()["api_key"], equal_to("sk-second"))
        client._key_info.side_effect = None
        client._key_info.return_value = {"team_id": str(context.organization.id), "blocked": True}
        assert_that(request(context, bank).status_code, equal_to(503))
        assert_that(client.generate_memory_key.call_count, equal_to(2))


def test_detached_memory_key_is_revoked_before_replacement(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client, bank = provision(context, monkeypatch)
        client._key_info.return_value = {"team_id": "another-team", "blocked": False}
        assert_that(request(context, bank).json()["api_key"], equal_to("sk-second"))
        assert_that(client.delete_key.call_args.args[0], equal_to(hashlib.sha256(b"sk-first").hexdigest()))


def test_failed_registration_revokes_the_provisioned_key(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client = context.injector.get(LiteLLMClient)
        monkeypatch.setattr(client, "generate_memory_key", Mock(return_value="sk-unregistered"))
        original = Session.commit

        def fail_registration(session):
            if any(isinstance(row, OrganizationMemoryKey) for row in session.new):
                raise OperationalError("commit", {}, Exception("database unavailable"))
            return original(session)

        monkeypatch.setattr(Session, "commit", fail_registration)
        with pytest.raises(OperationalError):
            request(context, f"org-{context.organization.id}")
        assert_that(client.delete_key.called, equal_to(True))
        assert_that(client.delete_key.call_args.args[0], equal_to(hashlib.sha256(b"sk-unregistered").hexdigest()))


def test_organization_deletion_revokes_its_memory_key(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client, _ = provision(context, monkeypatch)
        response = context.client.delete(
            f"/api/v1/organizations/{context.organization.id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(204), response.text)
        assert_that(client.delete_key.called, equal_to(True))


def test_deletion_cleanup_survives_proxy_outage_and_retries_in_reconciliation(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client, _ = provision(context, monkeypatch)
        client.delete_key.return_value = False
        response = context.client.delete(
            f"/api/v1/organizations/{context.organization.id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(204), response.text)
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        with Session(engine) as session:
            pending = session.exec(select(MemoryKeyRevocation)).all()
            assert_that(len(pending), equal_to(1))
            assert_that(pending[0].key_hash, equal_to(hashlib.sha256(b"sk-first").hexdigest()))
        client.delete_key.return_value = True
        context.injector.get(OrganizationLlmBudgetService).reconcile_llm_budgets()
        with Session(engine) as session:
            assert_that(session.exec(select(MemoryKeyRevocation)).all(), equal_to([]))


def test_changed_encryption_key_does_not_replace_or_erase_the_credential(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client, bank = provision(context, monkeypatch)
        context.injector.get(Config).agent_token_encryption_key = Fernet.generate_key().decode()
        assert_that(request(context, bank).status_code, equal_to(503))
        assert_that(client.generate_memory_key.call_count, equal_to(1))


def test_failed_registration_keeps_a_cleanup_retry_when_revocation_is_unavailable(monkeypatch):
    with given(agent_memory_api_setup(setup)) as context:
        client = context.injector.get(LiteLLMClient)
        monkeypatch.setattr(client, "generate_memory_key", Mock(return_value="sk-unregistered"))
        client.delete_key.return_value = False
        original = Session.commit

        def fail_registration(session):
            if any(isinstance(row, OrganizationMemoryKey) for row in session.new):
                raise OperationalError("commit", {}, Exception("registration unavailable"))
            return original(session)

        monkeypatch.setattr(Session, "commit", fail_registration)
        with pytest.raises(OperationalError):
            request(context, f"org-{context.organization.id}")
        engine = context.injector.get(PostgresRepositoryDelegate).engine
        with Session(engine) as session:
            pending = session.exec(select(MemoryKeyRevocation)).one()
            assert_that(pending.revoked_at, equal_to(None))
            assert_that(pending.key_hash, equal_to(hashlib.sha256(b"sk-unregistered").hexdigest()))
