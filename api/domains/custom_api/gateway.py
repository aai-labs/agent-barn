import hashlib
import json
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi_injector import Injected
from injector import inject, singleton
from starlette.concurrency import run_in_threadpool

from api.core.config import Config
from api.domains.custom_api.models import CustomApiRequest
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.request import RequestRefused, execute
from api.infrastructure.crypto import decrypt_token


@inject
@singleton
@dataclass
class CustomApiGateway:
    repository: CustomApiRepository
    config: Config

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
        try:
            return execute({"base_url": row.base_url, **credentials}, data.model_dump())
        except RequestRefused, ValueError, KeyError, TypeError:
            raise HTTPException(400, "Custom API request refused; check the configured scope and request") from None
        except Exception:
            raise HTTPException(502, "Custom API upstream unavailable") from None


custom_api_gateway_router = APIRouter()


@custom_api_gateway_router.post("/custom-api/request")
async def request_custom_api(
    data: CustomApiRequest,
    service: Annotated[CustomApiGateway, Injected(CustomApiGateway)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    return await run_in_threadpool(service.request, authorization, data)
