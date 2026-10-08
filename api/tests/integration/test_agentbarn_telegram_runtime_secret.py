from hamcrest import assert_that, equal_to, has_length, is_not, none
from sqlmodel import Session, select

from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService
from api.domains.communications.models import AgentBarnTelegramConnectionSecret, CommunicationConnection
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token


def _agent_with_connection(key: str, name: str):
    def step(context):
        there_is_an_agent(name=name)(context)
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
        )
        context.injector.get(PostgresRepositoryDelegate).save(connection)
        setattr(context, key, connection)

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    _agent_with_connection("first", "First Agent"),
    _agent_with_connection("second", "Second Agent"),
]


def _service(context) -> AgentBarnTelegramService:
    return context.injector.get(AgentBarnTelegramService)


def _stored(context) -> list[AgentBarnTelegramConnectionSecret]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramConnectionSecret)))


def test_a_connection_gets_its_own_secret_once_and_keeps_it() -> None:
    with given(_GIVEN) as context:
        with when("the first Agent starts twice and the second once"):
            first = _service(context).runtime_secret(context.first.id, create=True)
            again = _service(context).runtime_secret(context.first.id, create=True)
            second = _service(context).runtime_secret(context.second.id, create=True)

        with then("each Connection keeps one secret of its own, stored only encrypted"):
            assert first is not None
            assert_that(again, equal_to(first))
            assert_that(second, is_not(equal_to(first)))
            assert_that(first, has_length(43))
            assert_that(_stored(context), has_length(2))
            assert all(first not in row.secret_encrypted for row in _stored(context))


def test_reading_never_creates_a_secret() -> None:
    with given(_GIVEN) as context:
        with when("the proxy or relay looks up a Connection whose Agent never started with it"):
            secret = _service(context).runtime_secret(context.first.id, create=False)

        with then("there is none, and none is made"):
            assert_that(secret, none())
            assert_that(_stored(context), equal_to([]))


def test_deleting_a_connection_deletes_its_secret() -> None:
    with given(_GIVEN) as context:
        _service(context).runtime_secret(context.first.id, create=True)

        with when("the Connection row is deleted"):
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                session.delete(session.get(CommunicationConnection, context.first.id))
                session.commit()

        with then("its secret goes with it"):
            assert_that(_stored(context), equal_to([]))
