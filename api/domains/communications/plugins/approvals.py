APPROVAL_METADATA_KEY = "approval_id"
SYNTHESIZED_MESSAGE_PREFIX = "action:"
APPROVAL_CHOICE_LABELS = {
    "once": "Allow once",
    "session": "Allow for session",
    "always": "Always allow",
    "deny": "Deny",
}


def is_synthesized_message_id(message_id: str | None) -> bool:
    return message_id is not None and message_id.startswith(SYNTHESIZED_MESSAGE_PREFIX)


def encode_approval_value(approval_id: str, choice: str) -> str:
    return f"{approval_id}:{choice}"


def decode_approval_value(value: str) -> tuple[str, str]:
    approval_id, _, choice = value.rpartition(":")
    return approval_id, choice
