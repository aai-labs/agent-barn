"""Credential gateway HTTP surface.

Machine-to-machine only: the caller is an agent pod authenticating with its own gateway
token, exactly as the Ingest and Communications runtime routes work. There is no
user-facing surface here and therefore no Agent Access/Permission check — a Gateway Token
is issued by agent start and never listed, created, or mutated by a user. Adding any
operator-facing token endpoint later would put it squarely under
``docs/features/rbac/IMPLEMENTATION-BRIEF.md``.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi_injector import Injected

from api.domains.credential_gateway.models import GatewayTokenResolution
from api.domains.credential_gateway.service import (
    CredentialGatewayService,
    GatewayTokenRejected,
)

SUPPORTED_GATEWAY_PROTOCOL_VERSION = "1"

gateway_router = APIRouter(tags=["credential-gateway"])


@gateway_router.get("/identity", response_model=GatewayTokenResolution)
def resolve_identity(
    service: Annotated[CredentialGatewayService, Injected(CredentialGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> GatewayTokenResolution:
    """Resolve the presented gateway token to its Agent, Organization, and provider.

    Exists so the identity half of the gateway is independently deployable and testable
    before any request forwarding lands. Returns no credential material.
    """
    try:
        return service.resolve(authorization)
    except GatewayTokenRejected as exc:
        # One structured 403 for every rejection: an agent must not be able to tell an
        # unknown token from a revoked one. The distinction lives in the audit trail.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "gateway_token_rejected",
                "message": "The presented gateway token is not valid for this request.",
            },
        ) from exc
