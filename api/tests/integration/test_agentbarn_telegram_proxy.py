import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, is_in
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_proxy import AgentBarnTelegramProxy
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.agentbarn_telegram_service import hash_link_token
from api.domains.communications.models import AgentBarnTelegramLink, CommunicationConnection
from api.domains.communications.plugins.agentbarn_telegram import runtime_api_token
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_communications_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_REAL_TOKEN = "424242:the-real-shared-bot-token"
_JANE = 5550001
_STRANGER = 9990009
_BOT = {"id": 424242, "is_bot": True, "first_name": "Agent Barn", "username": "AgentBarnTestBot"}


class Telegram:
    """The real Bot API: records what reached it and answers each method."""

    def __init__(self) -> None:
        self.received: list[httpx.Request] = []
        self.answers: dict[str, tuple[int, dict]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": _BOT})
        status_code, body = self.answers.get(method, (200, {"ok": True, "result": {"message_id": 77}}))
        return httpx.Response(status_code, json=body)

    def methods(self) -> list[str]:
        return [request.url.path.rsplit("/", 1)[-1] for request in self.received]


def _connection(key: str, driver_key: str):
    def step(context):
        there_is_an_agent(name=key)(context)
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
            driver_key_encrypted=encrypt_token(driver_key, TEST_ENCRYPTION_KEY),
        )
        context.injector.get(PostgresRepositoryDelegate).save(connection)
        setattr(context, key, connection)
        setattr(context, f"{key}_token", runtime_api_token(driver_key, _REAL_TOKEN))

    return step


def _link(key: str, telegram_user_id: int):
    def step(context):
        connection = getattr(context, key)
        repository = context.injector.get(AgentBarnTelegramRepository)
        raw = f"link-{key}-{telegram_user_id}"
        repository.create_link_token(
            organization_id=connection.organization_id,
            agent_id=connection.agent_id,
            connection_id=connection.id,
            requested_by_membership_id=context.organization_user.id,
            token_hash=hash_link_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        repository.consume_link_token(
            hash_link_token(raw), telegram_user_id=telegram_user_id, telegram_username=None, now=datetime.now(UTC)
        )

    return step


def _fake_telegram(context) -> None:
    context.telegram = Telegram()
    context.injector.get(AgentBarnTelegramProxy).client = httpx.Client(transport=httpx.MockTransport(context.telegram))


_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "AGENTBARN_TELEGRAM_BOT_TOKEN": _REAL_TOKEN,
            "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_communications_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    _connection("sales", "sales-driver-key"),
    _connection("support", "support-driver-key"),
    _link("sales", _JANE),
    _link("support", 5550002),
    _fake_telegram,
]


def _url(context, method: str, *, key: str = "sales", token: str | None = None) -> str:
    connection = getattr(context, key)
    return f"/communications/v1/telegram/{connection.id}/bot{token or getattr(context, f'{key}_token')}/{method}"


def _call(context, method: str, payload: dict | None = None, **kwargs) -> httpx.Response:
    return context.communications_client.post(_url(context, method, **kwargs), json=payload or {})


def test_each_connection_has_its_own_stand_in_token_shaped_like_a_bot_token() -> None:
    sales = runtime_api_token("sales-driver-key", _REAL_TOKEN)

    assert sales.startswith("424242:")
    assert sales != runtime_api_token("support-driver-key", _REAL_TOKEN)
    assert "the-real-shared-bot-token" not in sales


@pytest.mark.parametrize("token", ["424242:wrong", None])
def test_a_wrong_or_another_connections_token_is_refused(token: str | None) -> None:
    with given(_GIVEN) as context:
        with when("the sales agent calls with a wrong token, or with the support agent's"):
            response = _call(
                context, "sendMessage", {"chat_id": _JANE, "text": "hi"}, token=token or context.support_token
            )

        with then("it is refused before reaching Telegram"):
            assert_that(response.status_code, equal_to(401))
            assert_that(response.json(), has_entries(ok=False, error_code=401))
            assert_that(context.telegram.received, equal_to([]))


def test_a_retired_connection_can_no_longer_call() -> None:
    with given(_GIVEN) as context:
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            connection = session.get(CommunicationConnection, context.sales.id)
            assert connection is not None
            connection.retired_at = datetime.now(UTC)
            session.add(connection)
            session.commit()

        with when("its agent calls"):
            response = _call(context, "sendMessage", {"chat_id": _JANE, "text": "hi"})

        with then("it is refused"):
            assert_that(response.status_code, equal_to(401))


def test_get_me_describes_the_shared_bot_and_is_cached() -> None:
    with given(_GIVEN) as context:
        with when("both agents ask who the bot is"):
            first = _call(context, "getMe")
            second = _call(context, "getMe", key="support")

        with then("they get the real bot, fetched from Telegram once with the real token"):
            assert_that(first.json(), equal_to({"ok": True, "result": _BOT}))
            assert_that(second.json(), equal_to(first.json()))
            assert_that(context.telegram.methods(), equal_to(["getMe"]))
            assert_that(context.telegram.received[0].url.path, equal_to(f"/bot{_REAL_TOKEN}/getMe"))


@pytest.mark.parametrize(
    "method",
    ["setWebhook", "deleteWebhook", "setMyCommands", "deleteMyCommands", "setMyDescription", "logOut", "close"],
)
def test_calls_that_would_change_the_shared_bot_succeed_without_reaching_telegram(method: str) -> None:
    with given(_GIVEN) as context:
        with when(f"an agent calls {method} as its runtime does at startup"):
            response = _call(context, method, {"url": "http://agent/telegram", "drop_pending_updates": True})

        with then("it is told it succeeded, and Telegram never sees it"):
            assert_that(response.json(), equal_to({"ok": True, "result": True}))
            assert_that(context.telegram.received, equal_to([]))


def test_webhook_info_reports_nothing_pending() -> None:
    with given(_GIVEN) as context:
        response = _call(context, "getWebhookInfo")

        assert_that(response.json(), has_entries(ok=True, result=has_entries(pending_update_count=0)))
        assert_that(context.telegram.received, equal_to([]))


@pytest.mark.parametrize("method", ["getUpdates", "getChatAdministrators", "banChatMember", "setChatTitle"])
def test_methods_outside_the_allowlist_are_refused(method: str) -> None:
    with given(_GIVEN) as context:
        with when(f"an agent calls {method}"):
            response = _call(context, method, {"chat_id": _JANE})

        with then("it is refused before reaching Telegram"):
            assert_that(response.status_code, equal_to(403))
            assert_that(response.json(), has_entries(ok=False, error_code=403))
            assert_that(context.telegram.received, equal_to([]))


def test_a_message_to_a_linked_user_is_forwarded_unchanged_with_the_real_token() -> None:
    with given(_GIVEN) as context:
        context.telegram.answers["sendMessage"] = (200, {"ok": True, "result": {"message_id": 5}})
        payload = {"chat_id": _JANE, "text": "Here's your summary", "parse_mode": "HTML"}

        with when("the sales agent messages Jane, who is linked to it"):
            response = _call(context, "sendMessage", payload)

        with then("Telegram receives exactly that message, and its answer comes back"):
            forwarded = context.telegram.received[0]
            assert_that(forwarded.url.path, equal_to(f"/bot{_REAL_TOKEN}/sendMessage"))
            assert_that(json.loads(forwarded.content), equal_to(payload))
            assert_that(response.json(), equal_to({"ok": True, "result": {"message_id": 5}}))


@pytest.mark.parametrize("chat_id", [_STRANGER, 5550002, "@somechannel"])
def test_messages_to_anyone_not_linked_to_this_agent_are_refused(chat_id: int | str) -> None:
    with given(_GIVEN) as context:
        with when("the sales agent messages a stranger, the support agent's user, or a channel"):
            response = _call(context, "sendMessage", {"chat_id": chat_id, "text": "hi"})

        with then("it is refused before reaching Telegram"):
            assert_that(response.status_code, equal_to(403))
            assert_that(context.telegram.received, equal_to([]))


def test_copying_from_a_chat_not_linked_to_this_agent_is_refused() -> None:
    with given(_GIVEN) as context:
        response = _call(context, "copyMessage", {"chat_id": _JANE, "from_chat_id": 5550002, "message_id": 1})

        assert_that(response.status_code, equal_to(403))
        assert_that(context.telegram.received, equal_to([]))


def test_method_names_are_matched_without_regard_to_case() -> None:
    with given(_GIVEN) as context:
        response = _call(context, "SENDMESSAGE", {"chat_id": _STRANGER, "text": "hi"})

        assert_that(response.status_code, equal_to(403))
        assert_that(context.telegram.received, equal_to([]))


def test_a_form_encoded_typing_indicator_to_a_linked_user_is_forwarded() -> None:
    with given(_GIVEN) as context:
        body = f"chat_id={_JANE}&action=typing"

        response = context.communications_client.post(
            _url(context, "sendChatAction"),
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert_that(response.status_code, equal_to(200))
        assert_that(context.telegram.received[0].content.decode(), equal_to(body))


def test_a_file_upload_to_a_linked_user_is_forwarded_byte_for_byte() -> None:
    with given(_GIVEN) as context:
        request = httpx.Request(
            "POST",
            "http://test/upload",
            data={"chat_id": str(_JANE), "caption": "chart"},
            files={"photo": ("chart.png", b"\x89PNG-bytes", "image/png")},
        )
        body = request.read()

        with when("the agent sends Jane a photo"):
            response = context.communications_client.post(
                _url(context, "sendPhoto"), content=body, headers={"Content-Type": request.headers["Content-Type"]}
            )

        with then("Telegram receives the identical upload"):
            assert_that(response.status_code, equal_to(200))
            forwarded = context.telegram.received[0]
            assert_that(forwarded.content, equal_to(body))
            assert_that(forwarded.headers["Content-Type"], equal_to(request.headers["Content-Type"]))


def test_a_file_upload_to_someone_not_linked_is_refused() -> None:
    with given(_GIVEN) as context:
        request = httpx.Request(
            "POST",
            "http://test/upload",
            data={"chat_id": str(_STRANGER)},
            files={"document": ("notes.txt", b"secret notes", "text/plain")},
        )

        response = context.communications_client.post(
            _url(context, "sendDocument"),
            content=request.read(),
            headers={"Content-Type": request.headers["Content-Type"]},
        )

        assert_that(response.status_code, equal_to(403))
        assert_that(context.telegram.received, equal_to([]))


def test_button_answers_and_file_lookups_need_no_chat() -> None:
    with given(_GIVEN) as context:
        _call(context, "answerCallbackQuery", {"callback_query_id": "cb-1"})
        _call(context, "getFile", {"file_id": "file-1"})

        assert_that(context.telegram.methods(), contains_exactly("answerCallbackQuery", "getFile"))


def test_a_user_who_blocked_the_bot_is_unlinked_when_telegram_says_so() -> None:
    with given(_GIVEN) as context:
        blocked = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
        context.telegram.answers["sendMessage"] = (403, blocked)

        with when("the agent messages Jane after she blocked the bot"):
            response = _call(context, "sendMessage", {"chat_id": _JANE, "text": "hi"})

        with then("Telegram's answer is passed back and Jane's link ends"):
            assert_that((response.status_code, response.json()), equal_to((403, blocked)))
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                active = session.exec(
                    select(AgentBarnTelegramLink).where(
                        col(AgentBarnTelegramLink.telegram_user_id) == _JANE,
                        col(AgentBarnTelegramLink.unlinked_at).is_(None),
                    )
                ).all()
            assert_that(active, equal_to([]))


def test_query_string_parameters_are_checked_and_forwarded_like_a_body() -> None:
    with given(_GIVEN) as context:
        with when("an agent passes parameters in the query string"):
            refused = context.communications_client.get(_url(context, "sendMessage"), params={"chat_id": _STRANGER})
            looked_up = context.communications_client.get(_url(context, "getFile"), params={"file_id": "file-1"})

        with then("the chat rule still applies, and allowed calls reach Telegram with the same parameters"):
            assert_that(refused.status_code, equal_to(403))
            assert_that(looked_up.status_code, equal_to(200))
            assert_that(json.loads(context.telegram.received[0].content), equal_to({"file_id": "file-1"}))


def _file_url(context, file_path: str, *, token: str | None = None) -> str:
    return f"/communications/v1/telegram/{context.sales.id}/file/bot{token or context.sales_token}/{file_path}"


class TelegramFiles(Telegram):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received.append(request)
        if request.url.path.endswith("/photos/file_7.jpg"):
            return httpx.Response(200, content=b"\xff\xd8jpeg-bytes", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})


def _fake_telegram_files(context) -> None:
    context.telegram = TelegramFiles()
    context.injector.get(AgentBarnTelegramProxy).client = httpx.Client(transport=httpx.MockTransport(context.telegram))


def test_an_agent_downloads_a_file_a_user_sent_through_the_real_bot() -> None:
    with given([*_GIVEN, _fake_telegram_files]) as context:
        with when("the agent downloads a photo Jane sent"):
            response = context.communications_client.get(_file_url(context, "photos/file_7.jpg"))

        with then("it gets the file, fetched with the real token"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.content, equal_to(b"\xff\xd8jpeg-bytes"))
            assert_that(response.headers["content-type"], equal_to("image/jpeg"))
            assert_that(context.telegram.received[0].url.path, equal_to(f"/file/bot{_REAL_TOKEN}/photos/file_7.jpg"))


def test_a_file_download_needs_the_connections_own_token() -> None:
    with given([*_GIVEN, _fake_telegram_files]) as context:
        response = context.communications_client.get(
            _file_url(context, "photos/file_7.jpg", token=context.support_token)
        )

        assert_that(response.status_code, equal_to(401))
        assert_that(context.telegram.received, equal_to([]))


@pytest.mark.parametrize(
    "file_path",
    ["../../bot424242:x/getUpdates", "photos/../../getUpdates", "photos/%2e%2e/%2e%2e/getUpdates"],
)
def test_a_file_path_cannot_reach_anything_but_a_file(file_path: str) -> None:
    with given([*_GIVEN, _fake_telegram_files]) as context:
        response = context.communications_client.get(_file_url(context, file_path))

        # Whichever route the path resolves to, the real token never leaves for it.
        assert_that(response.status_code, is_in([401, 404]))
        assert_that(context.telegram.received, equal_to([]))
