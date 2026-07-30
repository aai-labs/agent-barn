from typing import Any
from uuid import UUID

from dramatiq.brokers.redis import RedisBroker


def build_redis_broker(*, url: str, namespace: str) -> RedisBroker:
    return RedisBroker(url=url, namespace=namespace)


def first_arg_as_uuid(message: dict[str, Any]) -> UUID | None:
    args = message.get("args")
    if not isinstance(args, list | tuple) or not args:
        return None
    try:
        return UUID(str(args[0]))
    except (TypeError, ValueError):
        return None
