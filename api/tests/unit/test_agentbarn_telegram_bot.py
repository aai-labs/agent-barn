import json
from types import SimpleNamespace
from typing import cast

import httpx

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramBot
from api.domains.communications.agentbarn_telegram_rate_limit import AgentBarnTelegramRateLimits

_TOKEN = "424242:the-real-shared-bot-token"


def _bot(handler, *, bot_per_second: float = 25) -> AgentBarnTelegramBot:
    config = cast(
        Config,
        SimpleNamespace(
            agentbarn_telegram_bot_token=_TOKEN,
            agentbarn_telegram_bot_rate_per_second=bot_per_second,
            agentbarn_telegram_organization_rate_per_second=5,
        ),
    )
    bot = AgentBarnTelegramBot(config=config, limits=AgentBarnTelegramRateLimits(config))
    bot.client = httpx.Client(transport=httpx.MockTransport(handler))
    return bot


def test_the_bot_tries_once_and_never_sleeps_on_a_failure() -> None:
    calls: list[httpx.Request] = []

    def failing(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"ok": False})

    assert _bot(failing).send(1, "hi") is False
    assert len(calls) == 1


def test_courtesy_messages_are_skipped_when_the_shared_budget_is_spent() -> None:
    calls: list[httpx.Request] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    bot = _bot(telegram, bot_per_second=1)

    assert bot.send(1, "first", essential=False) is True
    assert bot.send(2, "second", essential=False) is False
    assert len(calls) == 1


def test_the_bot_and_the_agents_share_one_budget() -> None:
    def telegram(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    bot = _bot(telegram, bot_per_second=1)
    # An Agent's proxied call spends the bot-wide budget first.
    assert bot.limits.acquire_for_organization(None) == 0.0

    assert bot.send(1, "hi", essential=False) is False


def test_a_button_is_answered_with_the_real_token_as_a_courtesy() -> None:
    calls: list[httpx.Request] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    bot = _bot(telegram, bot_per_second=1)

    assert bot.answer_callback("cb-1", "This button is no longer active.") is True
    assert bot.answer_callback("cb-2", "This button is no longer active.") is False
    assert [request.url.path for request in calls] == [f"/bot{_TOKEN}/answerCallbackQuery"]
    assert json.loads(calls[0].content) == {"callback_query_id": "cb-1", "text": "This button is no longer active."}
