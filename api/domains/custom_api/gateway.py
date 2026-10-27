import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi_injector import Injected
from injector import inject, singleton
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.custom_api import request as engine
from api.domains.custom_api.models import CustomApiRequest
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.request import OAUTH2_CLIENT_CREDENTIALS, RequestRefused, TokenExchangeFailed, execute
from api.infrastructure.crypto import decrypt_token

#: Seconds of remaining validity below which a cached token is replaced rather than attached,
#: so a request never goes out with a token that expires in flight. A token that lives for
#: less than twice this keeps half its lifetime as the margin instead, so it is still reused.
TOKEN_EXPIRY_MARGIN = 60


@dataclass
class _CachedToken:
    value: str
    expires_at: float
    revision: str
    margin: float

    def usable(self, now: float) -> bool:
        return self.expires_at - now > self.margin


class AccessTokenCache:
    """Bearer tokens the gateway obtained for OAuth2 client-credentials connections.

    Held in process memory only, keyed by connection and credential revision: saving new
    client credentials or deleting the connection stops the old token being used without a
    restart, and nothing durable holds a live token. Each gateway process fills its own
    cache, which costs one token request per process per lifetime. A token the upstream
    rejects is discarded so the next request exchanges again instead of failing for the
    rest of the cached lifetime.
    """

    def __init__(self) -> None:
        self._tokens: dict[UUID, _CachedToken] = {}
        self._lock = threading.Lock()
        self._clock: Callable[[], float] = time.monotonic

    def access_token(self, connection_id: UUID, revision: str, auth: dict) -> str:
        with self._lock:
            cached = self._tokens.get(connection_id)
            if cached and cached.revision == revision and cached.usable(self._clock()):
                return cached.value
        # The exchange runs outside the lock: a slow token endpoint must not block every
        # other connection, and two concurrent exchanges for one connection are harmless.
        token, lifetime = engine.fetch_access_token(auth)
        fresh = _CachedToken(token, self._clock() + lifetime, revision, min(TOKEN_EXPIRY_MARGIN, lifetime / 2))
        with self._lock:
            cached = self._tokens.get(connection_id)
            # A concurrent exchange may have stored a token meanwhile; keep whichever lasts longer.
            if cached is None or cached.revision != revision or cached.expires_at < fresh.expires_at:
                self._tokens[connection_id] = fresh
                return token
            return cached.value

    def discard(self, connection_id: UUID, token: str) -> None:
        with self._lock:
            cached = self._tokens.get(connection_id)
            if cached and cached.value == token:
                del self._tokens[connection_id]


@inject
@singleton
@dataclass
class CustomApiGateway:
    repository: CustomApiRepository
    config: Config
    tokens: AccessTokenCache = field(default_factory=AccessTokenCache, init=False)

    def request(self, authorization: str | None, data: CustomApiRequest) -> dict:
        scheme, _, token = (authorization or "").partition(" ")
        row = (
            self.repository.authorize_token(hashlib.sha256(token.encode()).hexdigest())
            if scheme.lower() == "bearer" and token
            else None
        )
        if row is None:
            raise HTTPException(403, "Invalid Custom API connection credential")
        credentials = json.loads(decrypt_token(row.credentials_encrypted, self.config.agent_token_encryption_key))
        access_token = None
        if credentials.get("auth", {}).get("type") == OAUTH2_CLIENT_CREDENTIALS:
            revision = hashlib.sha256(row.credentials_encrypted.encode()).hexdigest()
            try:
                access_token = self.tokens.access_token(row.id, revision, credentials["auth"])
            except TokenExchangeFailed as exc:
                if exc.refused:
                    raise HTTPException(401, "The token endpoint refused the connection's client credentials") from None
                raise HTTPException(502, "Custom API token endpoint unavailable") from None
            except RequestRefused, ValueError, KeyError, TypeError:
                raise HTTPException(400, "Custom API token request refused; check the configured token URL") from None
        try:
            result = execute({"base_url": row.base_url, **credentials}, data.model_dump(), access_token=access_token)
        except RequestRefused, ValueError, KeyError, TypeError:
            raise HTTPException(400, "Custom API request refused; check the configured scope and request") from None
        except Exception:
            raise HTTPException(502, "Custom API upstream unavailable") from None
        if access_token is not None and result["status"] == 401:
            self.tokens.discard(row.id, access_token)
        return result


custom_api_gateway_router = APIRouter()


@custom_api_gateway_router.post("/custom-api/request")
async def request_custom_api(
    data: CustomApiRequest,
    service: Annotated[CustomApiGateway, Injected(CustomApiGateway)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    return await run_in_threadpool(service.request, authorization, data)
