"""Credential gateway HTTP surface.

Machine-to-machine only: the caller is an agent pod authenticating with its own gateway
token, exactly as the Ingest and Communications runtime routes work. There is no
user-facing surface here and therefore no Agent Access/Permission check — a Gateway Token
is issued by agent start and never listed, created, or mutated by a user. Adding any
operator-facing token endpoint later would put it squarely under
``docs/features/rbac/IMPLEMENTATION-BRIEF.md``.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi_injector import Injected

from api.domains.credential_gateway.forwarding import UpstreamUnreachable
from api.domains.credential_gateway.models import GatewayTokenResolution
from api.domains.credential_gateway.service import (
    CredentialGatewayService,
    ForwardRequest,
    GatewayForwardRefused,
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
        raise _refused("The presented gateway token is not valid for this request.") from exc


def _refused(detail_message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "gateway_token_rejected", "message": detail_message},
    )


@gateway_router.api_route(
    "/p/{provider_key}/{upstream_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def forward_to_provider(
    provider_key: str,
    upstream_path: str,
    request: Request,
    service: Annotated[CredentialGatewayService, Injected(CredentialGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Forward one agent request upstream under the provider's real credential.

    The agent addresses this exactly as it would address the provider's own API, so the
    only thing that changes on the agent side is the base URL and which token it sends.
    """
    body = await request.body()
    try:
        upstream = service.forward(
            authorization,
            ForwardRequest(
                provider_key=provider_key,
                path=upstream_path,
                method=request.method,
                headers=dict(request.headers),
                params=dict(request.query_params),
                body=body,
            ),
        )
    except (GatewayTokenRejected, GatewayForwardRefused) as exc:
        # Same opaque refusal as /identity: an agent must not learn whether its token was
        # unknown, revoked, aimed at the wrong provider, or rolled back.
        raise _refused("The presented gateway token is not valid for this request.") from exc
    except UpstreamUnreachable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "upstream_unreachable", "message": "The provider could not be reached."},
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=upstream.headers,
    )
