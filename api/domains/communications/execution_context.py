"""Server-issued provenance bound to one inbound delivery claim, never to origin labels."""

import hashlib
import hmac
from uuid import UUID


def issue_execution_token(secret: str, agent_id: UUID, delivery_id: UUID, attempt: int) -> str:
    payload = f"{agent_id}:{delivery_id}:{attempt}"
    signature = hmac.new(secret.encode(), f"agent-message:{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{delivery_id}:{attempt}:{signature}"


def read_execution_token(secret: str, agent_id: UUID, token: str) -> tuple[UUID, int]:
    try:
        delivery, attempt_text, _ = token.split(":")
        delivery_id, attempt = UUID(delivery), int(attempt_text)
        expected = issue_execution_token(secret, agent_id, delivery_id, attempt)
        if attempt < 1 or not hmac.compare_digest(token, expected):
            raise ValueError
        return delivery_id, attempt
    except ValueError as exc:
        raise PermissionError("Invalid inbound execution context") from exc
