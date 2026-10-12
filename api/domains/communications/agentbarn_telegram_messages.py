from typing import Any

# Parts of a Telegram message that are, or quote, other messages; those have owners of their own.
OTHER_MESSAGE_KEYS = frozenset({"reply_to_message", "external_reply", "quote", "pinned_message"})


def file_ids(message: Any) -> set[str]:
    """Every file id a Telegram message carries itself, leaving out the messages it quotes."""
    found: set[str] = set()
    if isinstance(message, dict):
        for key, value in message.items():
            if key in OTHER_MESSAGE_KEYS:
                continue
            if key == "file_id" and isinstance(value, str):
                found.add(value)
            else:
                found |= file_ids(value)
    elif isinstance(message, list):
        for value in message:
            found |= file_ids(value)
    return found
