from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, contains_exactly, equal_to
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.models import AgentBarnTelegramUpdate, AgentBarnTelegramUpdateStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
]


def _repo(context) -> AgentBarnTelegramRepository:
    return context.injector.get(AgentBarnTelegramRepository)


def _updates(context) -> list[AgentBarnTelegramUpdate]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramUpdate).order_by(col(AgentBarnTelegramUpdate.update_id))))


def _update(update_id: int) -> dict:
    return {"update_id": update_id, "message": {"chat": {"id": 1, "type": "private"}, "text": "hi"}}


def test_received_updates_are_stored_once_each() -> None:
    with given(_GIVEN) as context:
        with when("the same batch arrives twice, the second time with one new update"):
            first = _repo(context).store_updates([_update(10), _update(11)])
            second = _repo(context).store_updates([_update(11), _update(12)])

        with then("every update is stored exactly once, awaiting processing"):
            assert_that((first, second), equal_to((2, 1)))
            assert_that(
                [(update.update_id, update.status) for update in _updates(context)],
                contains_exactly(
                    (10, AgentBarnTelegramUpdateStatus.RECEIVED),
                    (11, AgentBarnTelegramUpdateStatus.RECEIVED),
                    (12, AgentBarnTelegramUpdateStatus.RECEIVED),
                ),
            )
            assert_that(_updates(context)[0].payload, equal_to(_update(10)))


def test_only_one_replica_polls_the_shared_bot_at_a_time() -> None:
    with given(_GIVEN) as context:
        repo = _repo(context)

        with when("two replicas claim the lease, and the first renews it"):
            first = repo.claim_ingress_lease("replica-a", now=_NOW)
            second = repo.claim_ingress_lease("replica-b", now=_NOW)
            renewed = repo.claim_ingress_lease("replica-a", now=_NOW + timedelta(seconds=10))

        with then("only the first replica holds it"):
            assert_that((first, second, renewed), equal_to((True, False, True)))


def test_an_expired_or_released_lease_can_be_taken_over() -> None:
    with given(_GIVEN) as context:
        repo = _repo(context)
        repo.claim_ingress_lease("replica-a", now=_NOW)

        with when("the lease expires, and later its new holder releases it"):
            after_expiry = repo.claim_ingress_lease("replica-b", now=_NOW + timedelta(minutes=5))
            repo.release_ingress_lease("replica-b")
            after_release = repo.claim_ingress_lease("replica-a", now=_NOW + timedelta(minutes=5))

        with then("another replica can take over each time"):
            assert_that((after_expiry, after_release), equal_to((True, True)))
