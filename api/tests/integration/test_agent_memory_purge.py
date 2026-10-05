import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, empty, equal_to, has_length, is_not, none
from sqlmodel import Session, select

from api.core.config import get_config
from api.domains.agent_memory.models import AgentMemoryGrant, AgentMemoryPurge
from api.domains.agent_memory.purge import MemoryPurger
from api.domains.agent_memory.purge_repository import MemoryPurgeRepository
from api.domains.agent_memory.repository import AgentMemoryRepository, stage_agent_memory_cleanup
from api.domains.agents.models import Agent
from api.infrastructure.hindsight.client import HindsightClient, HindsightResponse
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent_memory import agent_memory_api_setup, purge_tasks_are_clean, two_agents


def _setup():
    return agent_memory_api_setup(two_agents(), purge_tasks_are_clean())


def _delete(context):
    return context.client.delete(
        f"/api/v1/organizations/{{organization_id}}/agents/{context.billing.id}",
        headers={"Authorization": f"Bearer {context.access_token}"},
    )


def _rows(context, model):
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(select(model)).all()


def _due(context):
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        row = session.exec(select(AgentMemoryPurge)).one()
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(row)
        session.commit()


class Backend(HindsightClient):
    def __init__(self, agent_id):
        super().__init__(get_config())
        self.documents = [
            {
                "id": f"agent:{agent_id}:{scope}:doc-{index}",
                "tags": [f"author:{agent_id}", "scope:team"] if scope == "team" else [f"agent:{agent_id}"],
            }
            for index, scope in enumerate(["private", "team"])
        ]
        self.calls = []
        self.failure = None

    def request(self, method, path, payload, *, params=None):
        self.calls.append((method, path, params))
        if self.failure:
            raise HTTPException(self.failure, "upstream private error")
        if method == "DELETE":
            self.documents.pop(0)
            return HindsightResponse(200, b'{"success":true}')
        return HindsightResponse(200, json.dumps({"items": self.documents[:1], "total": len(self.documents)}).encode())


def test_delete_atomically_removes_both_grant_directions_and_queues_purge():
    with given(_setup()) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        context.billing.memory_key_hash = "b" * 64
        delegate.save(context.billing)
        for reader, source in [
            (context.billing, None),
            (context.triage, context.billing),
            (context.billing, context.triage),
            (context.triage, None),
        ]:
            delegate.save(
                AgentMemoryGrant(
                    organization_id=context.organization.id,
                    agent_id=reader.id,
                    source_agent_id=source.id if source else None,
                )
            )
        with when("the Agent is deleted"):
            response = _delete(context)
        with then("unrelated grants remain and cleanup is durable even without a backend"):
            assert_that(response.status_code, equal_to(204))
            grants = _rows(context, AgentMemoryGrant)
            assert_that(grants, has_length(1))
            assert_that(grants[0].agent_id, equal_to(context.triage.id))
            tasks = _rows(context, AgentMemoryPurge)
            assert_that(tasks, has_length(1))
            assert_that(tasks[0].agent_id, equal_to(context.billing.id))
            assert_that(tasks[0].organization_id, equal_to(context.organization.id))
            with Session(delegate.engine) as session:
                stored = session.get(Agent, context.billing.id)
                assert stored is not None
                assert_that(stored.memory_key_hash, none())


def test_cleanup_staging_rolls_back_with_its_transaction_and_is_idempotent():
    with given(_setup()) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        grant = AgentMemoryGrant(
            organization_id=context.organization.id, agent_id=context.triage.id, source_agent_id=context.billing.id
        )
        delegate.save(grant)
        with when("staging is rolled back, then repeated in one committed transaction"):
            with Session(delegate.engine) as session:
                stage_agent_memory_cleanup(session, context.billing.id, context.organization.id, datetime.now(UTC))
                session.rollback()
            assert_that(_rows(context, AgentMemoryPurge), empty())
            assert_that(_rows(context, AgentMemoryGrant)[0].id, equal_to(grant.id))
            with Session(delegate.engine) as session:
                for _ in range(2):
                    stage_agent_memory_cleanup(session, context.billing.id, context.organization.id, datetime.now(UTC))
                session.commit()
        with then("one task exists and the grant is removed"):
            assert_that(_rows(context, AgentMemoryPurge), has_length(1))
            assert_that(_rows(context, AgentMemoryGrant), empty())


def test_purge_retries_failures_and_resweeps_late_work_without_skipping_documents():
    with given(_setup()) as context:
        _delete(context)
        backend = Backend(context.billing.id)
        purger = MemoryPurger(context.injector.get(MemoryPurgeRepository), backend)
        backend.failure = 502
        with when("Hindsight is unavailable, then recovers, then a queued retain finishes late"):
            assert_that(purger.run_once(), equal_to(0))
            task = _rows(context, AgentMemoryPurge)[0]
            assert_that(task.last_error, equal_to("backend_502"))
            assert_that(task.attempts, equal_to(1))
            assert_that(task.last_cleaned_at, none())
            assert_that(purger.run_once(), equal_to(0))
            backend.failure = None
            _due(context)
            assert_that(purger.run_once(), equal_to(1))
            backend.documents.append(
                {"id": f"agent:{context.billing.id}:private:late", "tags": [f"agent:{context.billing.id}"]}
            )
            _due(context)
            assert_that(purger.run_once(), equal_to(1))
        with then("all own documents are gone and the tombstone remains for future sweeps"):
            assert_that(backend.documents, empty())
            task = _rows(context, AgentMemoryPurge)[0]
            assert_that(task.last_error, none())
            assert_that(task.last_cleaned_at, is_not(none()))
            assert_that(task.attempts, equal_to(0))
            for method, path, params in backend.calls:
                assert_that(
                    path.startswith(f"/v1/default/banks/org-{context.organization.id}/documents"), equal_to(True)
                )
                if method == "GET":
                    assert_that(
                        dict(params),
                        equal_to(
                            {
                                "tags": f"author:{context.billing.id}",
                                "tags_match": "any_strict",
                                "limit": "1",
                                "offset": "0",
                            }
                        ),
                    )


@pytest.mark.parametrize("bad", ["foreign-namespace", "foreign-tag", "missing-tags"])
def test_purge_refuses_documents_outside_its_owned_namespace_and_tags(bad):
    with given(_setup()) as context:
        _delete(context)
        backend = Backend(context.billing.id)
        if bad == "foreign-namespace":
            backend.documents[0]["id"] = f"agent:{context.triage.id}:private:foreign"
        elif bad == "foreign-tag":
            backend.documents[0]["tags"] = [f"agent:{context.triage.id}"]
        else:
            del backend.documents[0]["tags"]
        with when("the backend returns an unsafe target"):
            MemoryPurger(context.injector.get(MemoryPurgeRepository), backend).run_once()
        with then("nothing is deleted and a retry is recorded"):
            assert_that(any(call[0] == "DELETE" for call in backend.calls), equal_to(False))
            assert_that(_rows(context, AgentMemoryPurge)[0].last_error, equal_to("invalid_backend_response"))


def test_expired_leases_recover_and_stale_workers_cannot_finish_new_claims():
    with given(_setup()) as context:
        _delete(context)
        repository = context.injector.get(MemoryPurgeRepository)
        with when("a worker crashes while holding a lease"):
            old = repository.claim()
            assert_that(repository.claim(), none())
            with Session(repository.delegate.engine) as session:
                row = session.get(AgentMemoryPurge, old.id)
                assert row is not None
                row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
                session.add(row)
                session.commit()
            current = repository.claim()
            repository.finish(old, None)
        with then("a new worker owns the task and the old one cannot complete it"):
            row = _rows(context, AgentMemoryPurge)[0]
            assert_that(row.lease_id, equal_to(current.lease_id))
            assert_that(row.last_cleaned_at, none())


def test_live_or_mismatched_agents_cannot_be_purged_even_with_a_task():
    with given(_setup()) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        for org in [context.organization.id, uuid4()]:
            task = AgentMemoryPurge(agent_id=context.billing.id, organization_id=org)
            assert_that(context.injector.get(MemoryPurgeRepository).can_purge(task), equal_to(False))
        delegate.save(AgentMemoryPurge(agent_id=context.billing.id, organization_id=context.organization.id))
        backend = Backend(context.billing.id)
        with when("a tombstone incorrectly names a live Agent"):
            MemoryPurger(context.injector.get(MemoryPurgeRepository), backend).run_once()
        with then("the worker refuses the target"):
            assert_that(backend.calls, empty())
            assert_that(_rows(context, AgentMemoryPurge)[0].last_error, equal_to("target_not_deleted"))


def test_deadline_keeps_cleanup_pending():
    with given(_setup()) as context:
        _delete(context)
        backend = Backend(context.billing.id)
        row = context.injector.get(MemoryPurgeRepository).claim()
        with pytest.raises(HTTPException):
            MemoryPurger(context.injector.get(MemoryPurgeRepository), backend).purge(row, time.monotonic() - 1)
        assert_that(backend.calls, empty())


def test_operator_launcher_needs_only_database_and_backend_configuration():
    with given(_setup()) as context:
        _delete(context)
        with when("the operator launcher runs with no backend available"):
            result = subprocess.run(
                [sys.executable, "-c", "from api.domains.agent_memory.purge import main; main()"],
                cwd=Path(__file__).resolve().parents[3],
                env={
                    "PYTHON_DOTENV_DISABLED": "1",
                    "DB_CONNECTION_URL": context.injector.get(PostgresRepositoryDelegate).engine.url.render_as_string(
                        hide_password=False
                    ),
                    "SECRET_SIGNING_KEY": "",
                    "PLATFORM_ADMIN_CREDENTIALS": "",
                    "HINDSIGHT_BASE_URL": "",
                    "HINDSIGHT_API_KEY": "",
                },
                capture_output=True,
                check=False,
                timeout=30,
            )
        with then("it boots and records a generic retry instead of requiring user credentials"):
            assert_that(result.returncode, equal_to(0))
            assert_that(_rows(context, AgentMemoryPurge)[0].last_error, equal_to("backend_503"))


def test_a_grant_cannot_be_inserted_after_its_prevalidated_source_is_deleted(monkeypatch):
    with given(_setup()) as context:
        repository = context.injector.get(AgentMemoryRepository)
        original = repository.create_grant_with_event

        def delete_before_insert(*args, **kwargs):
            assert_that(_delete(context).status_code, equal_to(204))
            return original(*args, **kwargs)

        monkeypatch.setattr(repository, "create_grant_with_event", delete_before_insert)
        with when("the source disappears after authorization but before inserting its grant"):
            result = context.client.post(
                "/api/v1/organizations/{organization_id}/memory-grants",
                json={"agent_id": str(context.triage.id), "source_agent_id": str(context.billing.id)},
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
        with then("the stale grant is rejected and not stored"):
            assert_that(result.status_code, equal_to(404))
            assert_that(_rows(context, AgentMemoryGrant), empty())


def test_retry_after_partial_document_deletion_removes_only_the_remaining_document():
    class PartialBackend(Backend):
        failed_once = False

        def request(self, method, path, payload, *, params=None):
            if method == "DELETE" and len(self.documents) == 1 and not self.failed_once:
                self.failed_once = True
                raise HTTPException(502, "unavailable")
            return super().request(method, path, payload, params=params)

    with given(_setup()) as context:
        _delete(context)
        backend = PartialBackend(context.billing.id)
        purger = MemoryPurger(context.injector.get(MemoryPurgeRepository), backend)
        with when("one deletion succeeds and the next fails before retrying"):
            assert_that(purger.run_once(), equal_to(0))
            assert_that(backend.documents, has_length(1))
            _due(context)
            assert_that(purger.run_once(), equal_to(1))
        with then("the retry starts at offset zero and deletes only what remains"):
            assert_that(backend.documents, empty())
            assert_that([method for method, _, _ in backend.calls].count("DELETE"), equal_to(2))


def test_an_absent_bank_is_a_successful_empty_sweep():
    with given(_setup()) as context:
        _delete(context)
        backend = Backend(context.billing.id)
        backend.failure = 404
        with when("the deleted Agent never created a bank"):
            result = MemoryPurger(context.injector.get(MemoryPurgeRepository), backend).run_once()
        with then("cleanup succeeds without issuing a deletion"):
            assert_that(result, equal_to(1))
            assert_that(_rows(context, AgentMemoryPurge)[0].last_error, none())
            assert_that(any(method == "DELETE" for method, _, _ in backend.calls), equal_to(False))


def test_old_clean_tombstones_back_off_to_daily_sweeps():
    with given(_setup()) as context:
        _delete(context)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.exec(select(AgentMemoryPurge)).one()
            row.created_at = datetime.now(UTC) - timedelta(days=3)
            session.add(row)
            session.commit()
        repository = context.injector.get(MemoryPurgeRepository)
        claimed = repository.claim()
        assert claimed is not None
        repository.finish(claimed, None)
        row = _rows(context, AgentMemoryPurge)[0]
        assert row.last_cleaned_at is not None
        assert timedelta(hours=23) < row.next_attempt_at - row.last_cleaned_at <= timedelta(days=1)
