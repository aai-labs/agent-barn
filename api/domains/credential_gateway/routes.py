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
from starlette.concurrency import run_in_threadpool

from api.domains.credential_gateway.forwarding import UpstreamUnreachable
from api.domains.credential_gateway.models import BrokeredTokenRead, GatewayTokenResolution
from api.domains.credential_gateway.service import (
    CredentialGatewayService,
    ForwardRequest,
    GatewayForwardRefused,
    GatewayTokenRejected,
)
from api.domains.credential_gateway.sharepoint_broker import (
    SharePointHandoff,
    SharePointHandoffRefused,
    SharePointReconnectRequired,
)
from api.domains.integrations.plugins.base import UpstreamAuthenticationError

SUPPORTED_GATEWAY_PROTOCOL_VERSION = "1"

gateway_router = APIRouter(tags=["credential-gateway"])


@gateway_router.get("/identity", response_model=GatewayTokenResolution)
async def resolve_identity(
    service: Annotated[CredentialGatewayService, Injected(CredentialGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> GatewayTokenResolution:
    """Resolve the presented gateway token to its Agent, Organization, and provider.

    Exists so the identity half of the gateway is independently deployable and testable
    before any request forwarding lands. Returns no credential material.
    """
    try:
        return await run_in_threadpool(service.resolve, authorization)
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
        upstream = await run_in_threadpool(
            service.forward,
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


@gateway_router.api_route("/token", methods=["GET", "POST"], response_model=BrokeredTokenRead)
async def mint_upstream_token(
    service: Annotated[CredentialGatewayService, Injected(CredentialGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> BrokeredTokenRead:
    """Mint a short-lived upstream credential for a ``TOKEN_BROKER`` provider.

    Used by the agent-side `gog` shim, which exports the result as ``GOG_ACCESS_TOKEN``
    and execs the real binary. The refresh token and OAuth client secret never leave the
    gateway; only this expiring access token does.
    """
    try:
        minted = await run_in_threadpool(service.mint_upstream_token, authorization)
    except (GatewayTokenRejected, GatewayForwardRefused) as exc:
        raise _refused("The presented gateway token is not valid for this request.") from exc
    except SharePointHandoffRefused as exc:
        raise _refused("The presented gateway token is not valid for this request.") from exc
    except SharePointReconnectRequired as exc:
        raise HTTPException(
            409,
            detail={
                "error": "sharepoint_reconnect_required",
                "message": "Reconnect SharePoint before retrying this operation.",
            },
        ) from exc
    except UpstreamAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "upstream_unreachable", "message": "The provider could not be reached."},
        ) from exc
    return BrokeredTokenRead(
        access_token=minted.value,
        expires_in=minted.expires_in,
        scopes=sorted(minted.scopes),
    )


@gateway_router.post("/sharepoint/handoff", status_code=204)
async def handoff_sharepoint(
    data: SharePointHandoff,
    service: Annotated[CredentialGatewayService, Injected(CredentialGatewayService)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    try:
        await run_in_threadpool(service.handoff_sharepoint, authorization, data)
    except (GatewayTokenRejected, SharePointHandoffRefused) as exc:
        raise _refused("The presented gateway token is not valid for this handoff.") from exc
    except SharePointReconnectRequired as exc:
        raise HTTPException(
            409,
            detail={
                "error": "sharepoint_reconnect_required",
                "message": "Reconnect SharePoint before retrying this operation.",
            },
        ) from exc
    except UpstreamAuthenticationError as exc:
        raise HTTPException(
            502,
            detail={"error": "upstream_unreachable", "message": "SharePoint authentication could not be completed."},
        ) from exc
    return Response(status_code=204)
