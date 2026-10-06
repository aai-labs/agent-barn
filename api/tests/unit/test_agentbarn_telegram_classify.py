import pytest

from api.domains.communications.agentbarn_telegram_processor import UpdateKind, classify_update

_USER = {"id": 5550001, "is_bot": False, "first_name": "Jane", "username": "jane_doe"}
_PRIVATE = {"id": 5550001, "type": "private", "first_name": "Jane"}
_GROUP = {"id": -100123, "type": "supergroup", "title": "Team"}


def _message(text: str, chat: dict = _PRIVATE, key: str = "message") -> dict:
    return {"update_id": 1, key: {"message_id": 9, "from": _USER, "chat": chat, "date": 0, "text": text}}


def test_a_private_message_is_routed_to_the_senders_agent() -> None:
    classified = classify_update(_message("What's on today?"))

    assert classified.kind == UpdateKind.ROUTE
    assert (classified.telegram_user_id, classified.chat_id) == (5550001, 5550001)
    assert (classified.first_name, classified.username) == ("Jane", "jane_doe")


def test_an_edited_private_message_is_routed_too() -> None:
    assert classify_update(_message("fixed typo", key="edited_message")).kind == UpdateKind.ROUTE


@pytest.mark.parametrize("text", ["/start abcDEF_123-xyz", "/start@AgentBarnTestBot abcDEF_123-xyz"])
def test_a_start_command_with_a_token_links_the_account(text: str) -> None:
    classified = classify_update(_message(text))

    assert classified.kind == UpdateKind.LINK
    assert classified.link_token == "abcDEF_123-xyz"


def test_a_bare_start_command_is_an_ordinary_message() -> None:
    # Telegram sends a plain /start when someone opens the bot without a deep link.
    assert classify_update(_message("/start")).kind == UpdateKind.ROUTE


def test_a_button_press_in_a_private_chat_is_routed() -> None:
    update = {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": _USER,
            "message": {"message_id": 10, "chat": _PRIVATE, "date": 0},
            "data": "approve",
        },
    }

    classified = classify_update(update)

    assert (classified.kind, classified.telegram_user_id, classified.chat_id) == (
        UpdateKind.ROUTE,
        5550001,
        5550001,
    )


def test_blocking_the_bot_ends_the_link() -> None:
    update = {
        "update_id": 3,
        "my_chat_member": {
            "chat": _PRIVATE,
            "from": _USER,
            "date": 0,
            "old_chat_member": {"status": "member", "user": {"id": 1, "is_bot": True, "first_name": "Bot"}},
            "new_chat_member": {"status": "kicked", "user": {"id": 1, "is_bot": True, "first_name": "Bot"}},
        },
    }

    classified = classify_update(update)

    assert (classified.kind, classified.telegram_user_id) == (UpdateKind.BLOCKED, 5550001)


def test_unblocking_the_bot_needs_no_action() -> None:
    update = {
        "update_id": 4,
        "my_chat_member": {
            "chat": _PRIVATE,
            "from": _USER,
            "date": 0,
            "new_chat_member": {"status": "member", "user": {"id": 1, "is_bot": True, "first_name": "Bot"}},
        },
    }

    assert classify_update(update).kind == UpdateKind.IGNORE


@pytest.mark.parametrize(
    "update",
    [
        _message("hello team", chat=_GROUP),
        _message("/start abcDEF_123-xyz", chat=_GROUP),
        {"update_id": 5, "message": {"message_id": 1, "chat": _PRIVATE, "date": 0, "text": "no sender"}},
        {"update_id": 6, "message": {"message_id": 1, "from": {**_USER, "is_bot": True}, "chat": _PRIVATE}},
        {"update_id": 7, "channel_post": {"message_id": 1, "chat": {"id": -1, "type": "channel"}}},
        {"update_id": 8},
    ],
)
def test_group_bot_and_unrecognised_updates_are_ignored(update: dict) -> None:
    assert classify_update(update).kind == UpdateKind.IGNORE
