import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    equal_to,
    has_item,
    has_properties,
    is_,
    is_not,
    none,
    not_none,
)
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_ingress import AgentBarnTelegramIngress
from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramUpdateProcessor
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.agentbarn_telegram_service import hash_link_token
from api.domains.communications.models import (
    AgentBarnTelegramLink,
    AgentBarnTelegramUpdate,
    AgentBarnTelegramUpdateStatus,
    CommunicationConnection,
)
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.telegram_link_events import unlink_reasons

_JANE = 5550001
_WEB_APP_URL = "https://app.agentbarn.test"


class RecordingBot:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.answered: list[tuple[str, str]] = []
        # The texts sent as courtesies, which give way when the shared budget is spent.
        self.courtesies: list[str] = []
        self.fail = fail

    def send(self, chat_id: int, text: str, *, essential: bool = True) -> bool:
        if self.fail:
            raise RuntimeError("Telegram is down")
        self.sent.append((chat_id, text))
        if not essential:
            self.courtesies.append(text)
        return True

    def answer_callback(self, callback_query_id: str, text: str) -> bool:
        self.answered.append((callback_query_id, text))
        return True


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


def _recording_bot(context) -> None:
    context.bot = RecordingBot()
    context.injector.get(AgentBarnTelegramUpdateProcessor).bot = context.bot


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "WEB_APP_URL": _WEB_APP_URL}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    _agent_with_connection("sales", "Sales Helper"),
    _agent_with_connection("support", "Support Desk"),
    _recording_bot,
]


def _repo(context) -> AgentBarnTelegramRepository:
    return context.injector.get(AgentBarnTelegramRepository)


def _issue(context, connection: CommunicationConnection, raw: str, *, expires_in=timedelta(minutes=10)) -> None:
    _repo(context).create_link_token(
        organization_id=connection.organization_id,
        agent_id=connection.agent_id,
        connection_id=connection.id,
        requested_by_membership_id=context.organization_user.id,
        token_hash=hash_link_token(raw),
        expires_at=datetime.now(UTC) + expires_in,
    )


_next_update_id = iter(range(1000, 10_000))


def _receive(context, update: dict) -> int:
    update_id = next(_next_update_id)
    _repo(context).store_updates([{**update, "update_id": update_id}])
    context.injector.get(AgentBarnTelegramUpdateProcessor).process_pending()
    return update_id


def _private(text: str, user: int = _JANE, first_name: str = "Jane") -> dict:
    sender = {"id": user, "is_bot": False, "first_name": first_name, "username": "jane_doe"}
    return {
        "message": {"message_id": 1, "from": sender, "chat": {"id": user, "type": "private"}, "date": 0, "text": text}
    }


def _stored(context, update_id: int) -> AgentBarnTelegramUpdate:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(
            select(AgentBarnTelegramUpdate).where(col(AgentBarnTelegramUpdate.update_id) == update_id)
        ).one()


def _active_links(context) -> list[AgentBarnTelegramLink]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramLink).where(col(AgentBarnTelegramLink.unlinked_at).is_(None))))


def test_starting_the_bot_with_a_link_connects_the_user_and_greets_them() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")

        with when("Jane presses Start on her link"):
            update_id = _receive(context, _private("/start token-sales"))

        with then("she is linked to the agent and greeted by name, and nothing is kept of the message"):
            assert_that([link.agent_id for link in _active_links(context)], contains_exactly(context.sales.agent_id))
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "Hi Jane! You're linked to Sales Helper. Send a message to get started.")),
            )
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )


def test_linking_another_agent_tells_the_user_they_switched() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _issue(context, context.support, "token-support")
        _receive(context, _private("/start token-sales"))

        with when("Jane links the second agent"):
            _receive(context, _private("/start token-support"))

        with then("she is told who she now talks to and who she no longer hears from"):
            assert_that(
                context.bot.sent[-1],
                equal_to(
                    (
                        _JANE,
                        "You're now talking to Support Desk. You won't get replies from Sales Helper here anymore.",
                    )
                ),
            )


def test_an_expired_link_asks_for_a_fresh_one() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-old", expires_in=timedelta(seconds=-1))

        with when("Jane presses Start on an expired link"):
            _receive(context, _private("/start token-old"))

        with then("she is asked to get a fresh one and nothing is linked"):
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "This link has expired. Go back to Agent Barn for a fresh one.")),
            )
            assert_that(_active_links(context), equal_to([]))


def test_a_used_or_unknown_link_asks_for_a_fresh_one() -> None:
    with given(_GIVEN) as context:
        with when("Jane presses Start on a link that was never issued"):
            _receive(context, _private("/start never-issued"))

        with then("she is told it is not valid"):
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (_JANE, "This link has already been used or isn't valid. Go back to Agent Barn for a fresh one.")
                ),
            )


def test_someone_pressing_start_on_bad_links_hears_once_a_minute_and_as_a_courtesy() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-old", expires_in=timedelta(seconds=-1))

        with when("Jane presses Start on an expired link and then on links that were never issued"):
            _receive(context, _private("/start token-old"))
            _receive(context, _private("/start never-issued"))
            _receive(context, _private("/start never-issued-either"))

        with then("she gets one reply, which does not use the bot's reserved capacity"):
            expired = "This link has expired. Go back to Agent Barn for a fresh one."
            assert_that(context.bot.sent, contains_exactly((_JANE, expired)))
            assert_that(context.bot.courtesies, contains_exactly(expired))


def test_a_good_link_is_confirmed_even_right_after_a_bad_one() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")

        with when("Jane presses Start on a bad link and then on her real one"):
            _receive(context, _private("/start never-issued"))
            _receive(context, _private("/start token-sales"))

        with then("she is still told she is linked, as a message the bot must send"):
            linked = "Hi Jane! You're linked to Sales Helper. Send a message to get started."
            assert_that(context.bot.sent[-1], equal_to((_JANE, linked)))
            assert_that(context.bot.courtesies, is_not(has_item(linked)))


def test_a_stranger_is_pointed_to_sign_up_and_reaches_no_agent() -> None:
    with given(_GIVEN) as context:
        with when("someone who never linked writes to the bot"):
            update_id = _receive(context, _private("hello?", user=7770007, first_name="Sam"))

        with then("they are pointed to sign up and the message is not kept"):
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (
                        7770007,
                        f"Hi! To talk to an agent here, sign up at {_WEB_APP_URL}/signup and connect Telegram from there.",
                    )
                ),
            )
            assert_that(_stored(context, update_id), has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED))


def test_a_linked_users_message_is_queued_for_their_agent() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        greeted = len(context.bot.sent)

        with when("Jane writes to her agent"):
            update_id = _receive(context, _private("What's on today?"))

        with then("the message waits for her agent, with its content, and the bot itself stays quiet"):
            assert_that(
                _stored(context, update_id),
                has_properties(
                    status=AgentBarnTelegramUpdateStatus.QUEUED,
                    agent_id=context.sales.agent_id,
                    connection_id=context.sales.id,
                    telegram_user_id=_JANE,
                    payload=not_none(),
                ),
            )
            assert_that(len(context.bot.sent), equal_to(greeted))


def test_a_user_whose_linker_lost_access_is_unlinked() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)

        with when("Jane writes after the member who linked her lost access to the agent"):
            update_id = _receive(context, _private("still there?"))

        with then("her link ends, the message reaches no agent, and she is pointed to sign up"):
            assert_that(_active_links(context), equal_to([]))
            assert_that(_stored(context, update_id), has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED))
            assert_that(context.bot.sent[-1][1], contains_string("sign up at"))
            assert_that(unlink_reasons(context), equal_to(["access_lost"]))


def test_blocking_the_bot_ends_the_link_silently() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        sent_before = len(context.bot.sent)
        blocked = {
            "my_chat_member": {
                "chat": {"id": _JANE, "type": "private"},
                "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                "date": 0,
                "new_chat_member": {"status": "kicked", "user": {"id": 1, "is_bot": True, "first_name": "Bot"}},
            }
        }

        with when("Jane blocks the bot"):
            _receive(context, blocked)

        with then("her link ends and nothing is sent to her"):
            assert_that(_active_links(context), equal_to([]))
            assert_that(len(context.bot.sent), equal_to(sent_before))
            assert_that(unlink_reasons(context), equal_to(["blocked_bot"]))


def test_group_messages_get_no_reply() -> None:
    with given(_GIVEN) as context:
        group = {"id": -100123, "type": "supergroup", "title": "Team"}

        with when("someone writes in a group the bot is in"):
            update_id = _receive(
                context,
                {
                    "message": {
                        "message_id": 1,
                        "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                        "chat": group,
                    }
                },
            )

        with then("the bot says nothing and the message is not kept"):
            assert_that(context.bot.sent, equal_to([]))
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )


def test_a_reply_that_cannot_be_sent_does_not_block_later_updates() -> None:
    with given(_GIVEN) as context:
        context.injector.get(AgentBarnTelegramUpdateProcessor).bot = RecordingBot(fail=True)
        _issue(context, context.sales, "token-sales")

        with when("Telegram rejects the greeting"):
            update_id = _receive(context, _private("/start token-sales"))

        with then("the link still stands and the update is settled"):
            assert_that([link.agent_id for link in _active_links(context)], contains_exactly(context.sales.agent_id))
            assert_that(_stored(context, update_id).status, is_(AgentBarnTelegramUpdateStatus.HANDLED))


def test_an_update_that_keeps_failing_is_given_up_after_a_few_tries() -> None:
    with given(_GIVEN) as context:
        repository = context.injector.get(AgentBarnTelegramRepository)
        with patch.object(repository, "find_routable_link", side_effect=RuntimeError("database blip")):
            with when("the same update fails on every pass"):
                update_id = _receive(context, _private("hello?", user=7770007))
                for minutes in range(1, 11):
                    context.injector.get(AgentBarnTelegramUpdateProcessor).process_pending(
                        now=datetime.now(UTC) + timedelta(minutes=minutes)
                    )

        with then("it is given up, without its content, instead of retrying forever"):
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )


def test_a_users_later_messages_wait_behind_one_that_failed() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        repository = context.injector.get(AgentBarnTelegramRepository)
        processor = context.injector.get(AgentBarnTelegramUpdateProcessor)
        real_find = repository.find_routable_link
        calls = {"n": 0}

        def fails_once(user_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database blip")
            return real_find(user_id)

        first = next(_next_update_id)
        second = next(_next_update_id)
        repository.store_updates(
            [{**_private("first"), "update_id": first}, {**_private("second"), "update_id": second}]
        )

        with patch.object(repository, "find_routable_link", side_effect=fails_once):
            with when("Jane's first message fails once, and is retried once it is due"):
                processor.process_pending()
                after_failure = (_stored(context, first).status, _stored(context, second).status)
                processor.process_pending()
                before_due = (_stored(context, first).status, _stored(context, second).status)
                processor.process_pending(now=datetime.now(UTC) + timedelta(minutes=1))

        with then("her second message waits behind it, then both are queued in order"):
            assert_that(
                after_failure,
                equal_to((AgentBarnTelegramUpdateStatus.RECEIVED, AgentBarnTelegramUpdateStatus.RECEIVED)),
            )
            assert_that(before_due, equal_to(after_failure))
            assert_that(
                (_stored(context, first).status, _stored(context, second).status),
                equal_to((AgentBarnTelegramUpdateStatus.QUEUED, AgentBarnTelegramUpdateStatus.QUEUED)),
            )


def test_a_stranger_gets_the_sign_up_reply_once_in_a_while_not_every_time() -> None:
    with given(_GIVEN) as context:
        with when("someone who never linked sends three messages in a row"):
            for text in ("hi", "hello?", "anyone?"):
                _receive(context, _private(text, user=7770007, first_name="Sam"))

        with then("they get the sign-up reply once"):
            assert_that([chat for chat, _ in context.bot.sent], equal_to([7770007]))


def _jane_message(message_id: int, **content) -> dict:
    sender = {"id": _JANE, "is_bot": False, "first_name": "Jane", "username": "jane_doe"}
    return {"message_id": message_id, "from": sender, "chat": {"id": _JANE, "type": "private"}, "date": 0, **content}


def _bot_message(message_id: int, text: str) -> dict:
    sender = {"id": 424242, "is_bot": True, "first_name": "Agent Barn"}
    return {"message_id": message_id, "from": sender, "chat": {"id": _JANE, "type": "private"}, "date": 0, "text": text}


def _jane_switches_from_support_to_sales(context) -> None:
    """Jane sent the support agent message 40, which answered with message 41; then she linked sales."""
    _issue(context, context.support, "token-support")
    _receive(context, _private("/start token-support"))
    _receive(context, {"message": _jane_message(40, text="Where is my order?")})
    _repo(context).record_ownership(context.support.id, messages=[(_JANE, 41)])
    _issue(context, context.sales, "token-sales")
    _receive(context, _private("/start token-sales"))
    context.bot.sent.clear()


def _owns(context, connection: CommunicationConnection, *, messages=(), files=()) -> bool:
    return _repo(context).owns_messages(connection.id, [(_JANE, m) for m in messages]) and _repo(context).owns_files(
        connection.id, files
    )


def test_a_users_message_and_its_files_become_their_agents() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))

        with when("Jane sends her agent a photo"):
            photo = [{"file_id": "file-small", "file_unique_id": "s"}, {"file_id": "file-large", "file_unique_id": "l"}]
            _receive(context, {"message": _jane_message(50, photo=photo, caption="receipt")})

        with then("the message and both sizes of the photo are her agent's, and no one else's"):
            assert_that(_owns(context, context.sales, messages=[50], files=["file-small", "file-large"]), is_(True))
            assert_that(_owns(context, context.support, messages=[50]), is_(False))
            assert_that(_owns(context, context.support, files=["file-large"]), is_(False))


def test_a_button_under_a_previous_agents_message_is_not_passed_on() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        with when("Jane presses a button under the support agent's old reply"):
            callback = {
                "id": "cb-1",
                "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                "message": _bot_message(41, "Your order ships Monday."),
                "data": "track",
            }
            update_id = _receive(context, {"callback_query": callback})

        with then("it reaches no agent, and Telegram is told the button no longer works"):
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )
            assert_that(context.bot.answered, contains_exactly(("cb-1", "This button is no longer active.")))
            assert_that(context.bot.sent, equal_to([]))


def test_a_button_under_the_current_agents_message_is_passed_on() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        _repo(context).record_ownership(context.sales.id, messages=[(_JANE, 60)])

        with when("Jane presses a button under the sales agent's message"):
            callback = {
                "id": "cb-2",
                "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                "message": _bot_message(60, "Pick a plan"),
                "data": "pro",
            }
            update_id = _receive(context, {"callback_query": callback})

        with then("it is queued for the sales agent"):
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.QUEUED, connection_id=context.sales.id),
            )
            assert_that(context.bot.answered, equal_to([]))


def test_an_edit_of_a_message_sent_to_a_previous_agent_is_not_passed_on() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        with when("Jane edits the message she sent the support agent"):
            update_id = _receive(context, {"edited_message": _jane_message(40, text="Where is my refund?")})

        with then("it reaches no agent, and the bot stays quiet"):
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )
            assert_that(context.bot.sent, equal_to([]))


def test_a_reply_to_a_previous_agents_message_reaches_the_new_agent_without_it() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        with when("Jane replies to the support agent's old message, quoting part of it"):
            reply = _jane_message(
                70,
                text="Is this still true?",
                reply_to_message=_bot_message(41, "Your order ships Monday."),
                quote={"text": "ships Monday", "position": 11},
            )
            update_id = _receive(context, {"message": reply})

        with then("the sales agent gets her words but not the support agent's message"):
            stored = _stored(context, update_id)
            assert_that(stored.status, equal_to(AgentBarnTelegramUpdateStatus.QUEUED))
            assert_that(stored.payload, not_none())
            assert stored.payload is not None
            assert_that(stored.payload["message"], equal_to(_jane_message(70, text="Is this still true?")))


def test_a_reply_to_the_current_agents_own_message_keeps_it() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        _repo(context).record_ownership(context.sales.id, messages=[(_JANE, 60)])

        with when("Jane replies to the sales agent's message"):
            reply = _jane_message(71, text="Yes", reply_to_message=_bot_message(60, "Shall I book it?"))
            update_id = _receive(context, {"message": reply})

        with then("the sales agent sees what she replied to"):
            stored = _stored(context, update_id)
            assert stored.payload is not None
            assert_that(stored.payload["message"], equal_to(reply))


def test_pinning_a_previous_agents_message_does_not_show_it_to_the_new_agent() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        with when("Jane pins the support agent's old message"):
            pinned = _jane_message(72, pinned_message=_bot_message(41, "Your order ships Monday."))
            update_id = _receive(context, {"message": pinned})

        with then("the sales agent is not shown the pinned message"):
            stored = _stored(context, update_id)
            assert stored.payload is not None
            assert_that(stored.payload["message"], equal_to(_jane_message(72)))


def test_an_edit_of_a_message_sent_to_the_current_agent_is_passed_on() -> None:
    with given([*_GIVEN, _jane_switches_from_support_to_sales]) as context:
        _receive(context, {"message": _jane_message(80, text="Book Tuesday")})

        with when("Jane edits the message she sent the sales agent"):
            update_id = _receive(context, {"edited_message": _jane_message(80, text="Book Wednesday")})

        with then("it is queued for the sales agent"):
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.QUEUED, connection_id=context.sales.id),
            )


_ADA = 7770007


def _ingress_pass(context) -> None:
    """One ingress cycle over what is stored, as the polling replica runs it."""
    ingress = context.injector.get(AgentBarnTelegramIngress)
    with patch.object(ingress, "poll_once", AsyncMock()), patch.object(ingress, "should_poll", return_value=True):
        asyncio.run(ingress.cycle(Mock()))


def test_one_users_failing_backlog_does_not_hold_up_another_user() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        repository = _repo(context)
        real_find = repository.find_routable_link

        def fails_for_ada(user_id):
            if user_id == _ADA:
                raise RuntimeError("database blip")
            return real_find(user_id)

        ada = [next(_next_update_id) for _ in range(6)]
        jane = next(_next_update_id)
        repository.store_updates(
            [
                *({**_private(f"ada {n}", user=_ADA), "update_id": u} for n, u in enumerate(ada)),
                {**_private("hi"), "update_id": jane},
            ]
        )

        with patch.object(repository, "find_routable_link", side_effect=fails_for_ada):
            with when("one ingress pass runs while every one of Ada's updates fails"):
                _ingress_pass(context)

        with then("Jane's later message is queued, and Ada's wait in order behind her first"):
            assert_that(_stored(context, jane).status, equal_to(AgentBarnTelegramUpdateStatus.QUEUED))
            assert_that(
                [(_stored(context, u).status, _stored(context, u).attempt_count) for u in ada],
                equal_to(
                    [(AgentBarnTelegramUpdateStatus.RECEIVED, 1)] + [(AgentBarnTelegramUpdateStatus.RECEIVED, 0)] * 5
                ),
            )
            assert_that(_stored(context, ada[0]).next_attempt_at, not_none())


def test_a_failed_update_without_a_sender_waits_out_its_own_backoff() -> None:
    with given(_GIVEN) as context:
        repository = _repo(context)
        processor = context.injector.get(AgentBarnTelegramUpdateProcessor)
        update_id = next(_next_update_id)
        repository.store_updates([{"update_id": update_id, "message": {"message_id": 1, "chat": {"id": -5}}}])

        with patch.object(repository, "settle_update", side_effect=RuntimeError("database blip")):
            with when("it fails, and the next pass runs straight away"):
                processor.process_pending()
                processor.process_pending()

        with then("it was tried once"):
            assert_that(_stored(context, update_id).attempt_count, equal_to(1))
