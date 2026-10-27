"""Purpose-separated capability, rotated with the Agent's existing per-start ingest secret."""

import hashlib
import hmac
from uuid import UUID


def runtime_token(agent_id: UUID, ingest_key: str) -> str:
    signature = hmac.new(ingest_key.encode(), b"agent-artifacts-v1", hashlib.sha256).hexdigest()
    return f"{agent_id}.{signature}"
