import logging
from types import SimpleNamespace
from urllib.parse import quote
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_proxy import (
    AgentBarnTelegramProxy,
    BadBotApiRequest,
    BotApiRequest,
    UploadedFile,
    parse_bot_api_request,
)
from api.domains.communications.agentbarn_telegram_rate_limit import AgentBarnTelegramRateLimits
from api.domains.communications.plugins.agentbarn_telegram import runtime_api_token
from api.infrastructure.crypto import encrypt_token
from api.tests.steps.agent import TEST_ENCRYPTION_KEY

_REAL_TOKEN = "424242:the-real-shared-bot-token"
_DRIVER_KEY = "driver-key"


def _proxy(handler) -> AgentBarnTelegramProxy:
    repository = Mock()
    repository.proxy_connection.return_value = SimpleNamespace(
        organization_id=uuid4(), driver_key_encrypted=encrypt_token(_DRIVER_KEY, TEST_ENCRYPTION_KEY)
    )
    repository.linked_user_ids.return_value = {5550001}
    config = cast(
        Config,
        SimpleNamespace(
            agentbarn_telegram_bot_token=_REAL_TOKEN,
            agent_token_encryption_key=TEST_ENCRYPTION_KEY,
            agentbarn_telegram_bot_rate_per_second=25,
            agentbarn_telegram_organization_rate_per_second=5,
        ),
    )
    proxy = AgentBarnTelegramProxy(config=config, repository=repository, limits=AgentBarnTelegramRateLimits(config))
    proxy.client = httpx.Client(transport=httpx.MockTransport(handler))
    return proxy


def _call(proxy: AgentBarnTelegramProxy, method: str, params: dict | None = None):
    return proxy.handle(
        uuid4(), runtime_api_token(_DRIVER_KEY, _REAL_TOKEN), method, request=BotApiRequest(params=params or {})
    )


def test_an_unreachable_telegram_is_reported_without_the_real_token(caplog: pytest.LogCaptureFixture) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with caplog.at_level(logging.DEBUG):
        response = _call(_proxy(unreachable), "sendMessage", {"chat_id": 5550001})

    assert response.status_code == 502
    assert "the-real-shared-bot-token" not in str(response.body)
    assert "the-real-shared-bot-token" not in caplog.text


def test_a_failed_bot_lookup_is_passed_on_and_not_cached() -> None:
    answers = [
        httpx.Response(500, json={"ok": False, "error_code": 500}),
        httpx.Response(200, json={"ok": True, "result": {"id": 424242}}),
    ]
    proxy = _proxy(lambda request: answers.pop(0))

    first = _call(proxy, "getMe")
    second = _call(proxy, "getMe")

    assert first.status_code == 500
    assert second.body == {"ok": True, "result": {"id": 424242}}


def test_an_answer_that_is_not_json_becomes_a_bad_gateway() -> None:
    response = _call(_proxy(lambda request: httpx.Response(200, text="<html>oops</html>")), "getFile", {"file_id": "f"})

    assert response.status_code == 502


@pytest.mark.parametrize(
    "file_path",
    ["../getUpdates", "photos/../../bot424242:x/getUpdates", "photos/..", "photos/%2e%2e/x", "photos/file.jpg?x=1", ""],
)
def test_only_plain_file_paths_are_fetched(file_path: str) -> None:
    requests: list[httpx.Request] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"x")

    proxy = _proxy(telegram)
    downloaded = proxy.download(uuid4(), runtime_api_token(_DRIVER_KEY, _REAL_TOKEN), file_path)

    assert downloaded.status_code == 404
    assert requests == []


def test_a_multipart_field_given_twice_is_refused() -> None:
    photo = UploadedFile("photo", "a.png", b"a", "image/png")
    with pytest.raises(BadBotApiRequest):
        parse_bot_api_request([], "multipart/form-data; boundary=x", b"", [("chat_id", "1"), ("chat_id", "2")])
    with pytest.raises(BadBotApiRequest):
        parse_bot_api_request([], "multipart/form-data; boundary=x", b"", [("photo", photo), ("photo", "file-id")])


@pytest.mark.parametrize("body", [b"[1, 2]", b"not json", b'"text"'])
def test_a_json_body_must_be_one_object(body: bytes) -> None:
    with pytest.raises(BadBotApiRequest):
        parse_bot_api_request([], "application/json", body)


def test_a_well_formed_request_is_read_with_its_encoding() -> None:
    photo = UploadedFile("photo", "a.png", b"png", "image/png")

    assert parse_bot_api_request([("chat_id", "1")], None, b"") == BotApiRequest(params={"chat_id": "1"})
    assert parse_bot_api_request([], "Application/Json; charset=utf-8", b'{"chat_id": 1}') == BotApiRequest(
        params={"chat_id": 1}
    )
    assert parse_bot_api_request([], "application/x-www-form-urlencoded", b"chat_id=1&text=") == BotApiRequest(
        params={"chat_id": "1", "text": ""}, encoding="form"
    )
    assert parse_bot_api_request(
        [], "multipart/form-data; boundary=x", b"", [("chat_id", "1"), ("photo", photo)]
    ) == BotApiRequest(params={"chat_id": "1"}, encoding="multipart", files=(photo,))


_FORM = "application/x-www-form-urlencoded"


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        (_FORM, b"chat_id=1&reply_parameters=" + quote('{"chat_id": 999, "chat_id": 1, "message_id": 7}').encode()),
        ("application/json", b'{"chat_id": 1, "reply_parameters": "{\\"chat_id\\": 999, \\"chat_id\\": 1}"}'),
        (_FORM, b"chat_id=1&reply_parameters=" + quote("{not json").encode()),
    ],
)
def test_reply_parameters_sent_as_text_are_read_as_strictly_as_the_body(content_type: str, body: bytes) -> None:
    # A JSON string the proxy read one way could be read another way by Telegram.
    with pytest.raises(BadBotApiRequest):
        parse_bot_api_request([], content_type, body)


def test_reply_parameters_sent_as_text_are_forwarded_as_read() -> None:
    body = b"chat_id=1&reply_parameters=" + quote('{ "chat_id":1,"message_id" : 7 }').encode()

    request = parse_bot_api_request([], _FORM, body)

    assert request.params["reply_parameters"] == '{"chat_id": 1, "message_id": 7}'


@pytest.mark.parametrize("chat_id", ["123\n", "\u0661\u0662\u0663", " 123", "+123"])
def test_only_plain_ascii_chat_ids_are_accepted(chat_id: str) -> None:
    assert AgentBarnTelegramProxy._named_chats({"chat_id": chat_id}) is None
