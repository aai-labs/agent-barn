APPROVAL_METADATA_KEY = "approval_id"
SYNTHESIZED_MESSAGE_PREFIX = "action:"
APPROVAL_COMPONENT_PREFIX = "agentbarn_approval"
APPROVAL_COMPONENT_SEPARATOR = "|"
APPROVAL_COMPONENT_MAX_CHARS = 100
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


def is_approval_component(value: str) -> bool:
    return value.startswith(f"{APPROVAL_COMPONENT_PREFIX}{APPROVAL_COMPONENT_SEPARATOR}")


def encode_approval_component(thread_id: str, approval_id: str, choice: str) -> str:
    return APPROVAL_COMPONENT_SEPARATOR.join((APPROVAL_COMPONENT_PREFIX, thread_id, approval_id, choice))


def decode_approval_component(value: str) -> tuple[str, str, str]:
    parts = value.split(APPROVAL_COMPONENT_SEPARATOR)
    if len(parts) != 4 or parts[0] != APPROVAL_COMPONENT_PREFIX:
        return "", "", ""
    return parts[1], parts[2], parts[3]
