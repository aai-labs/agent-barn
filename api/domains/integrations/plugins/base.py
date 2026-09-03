"""The Integration Plugin seam: one class per tool-Integration provider.

An Integration varies along two independent axes — the credential/provider and the
agent-side CLI that reaches it — so provider behavior lives here and CLI materialization
lives behind ``RuntimeToolAdapter``. See
``docs/adr/2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md``.

Plugins are imported by both the API (at agent start) and, once it exists, the credential
gateway (per request). They therefore depend only on credential models, stdlib, and the
HTTP client — never on routes, the SQLAlchemy session, or the Kubernetes client.
"""

from __future__ import annotations

import enum
from abc import ABC
from dataclasses import dataclass, field

from api.domains.agents.models import SecretContent, SecretProvider
from api.infrastructure.integration_validators.result import IntegrationValidationResult


class EgressMode(str, enum.Enum):
    """How a provider's real credential reaches the upstream service.

    See ``docs/adr/2026-09-02-credential-gateway-egress-modes.md``.
    """

    #: The gateway substitutes the real authorization on a forwarded request. The
    #: credential never enters the agent pod.
    GATEWAY_PROXY = "gateway_proxy"
    #: The gateway mints a short-lived upstream token the pod uses directly. The pod
    #: never holds a renewable grant.
    TOKEN_BROKER = "token_broker"
    #: The credential is materialized into the pod. Retained as the rollout fallback
    #: and as the recorded escape hatch for a CLI whose auth cannot be redirected.
    DIRECT = "direct"


@dataclass(frozen=True)
class OutboundRequest:
    """One upstream HTTP request a ``GATEWAY_PROXY`` plugin may re-authorize.

    The gateway has already stripped the agent's gateway token before a plugin sees
    this, so a plugin never has to remove it.
    """

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    sensitive_headers: frozenset[str] = frozenset()

    def with_headers(self, headers: dict[str, str], *, sensitive: bool = False) -> OutboundRequest:
        sensitive_headers = self.sensitive_headers
        if sensitive:
            sensitive_headers |= frozenset(name.lower() for name in headers)
        return OutboundRequest(
            self.method,
            self.path,
            {**self.headers, **headers},
            dict(self.query),
            sensitive_headers,
        )

    def with_query(self, query: dict[str, str]) -> OutboundRequest:
        return OutboundRequest(
            self.method,
            self.path,
            dict(self.headers),
            {**self.query, **query},
            self.sensitive_headers,
        )


@dataclass(frozen=True)
class MintedToken:
    """A short-lived upstream credential produced by a ``TOKEN_BROKER`` plugin."""

    value: str
    #: Seconds of remaining validity at the moment of minting. The pod re-fetches rather
    #: than tracking wall-clock expiry, so a relative lifetime avoids clock-skew bugs.
    expires_in: int
    scopes: frozenset[str] = frozenset()


class UpstreamAuthenticationError(Exception):
    """A plugin could not obtain the short-lived authorization needed to proxy."""


@dataclass(frozen=True)
class RuntimeArtifacts:
    """What a ``RuntimeToolAdapter`` contributes to one agent's pod.

    Deliberately carries no Kubernetes types, matching the existing pure string/dict
    builder convention in ``agents/aai_cli_artifacts.py`` and ``agents/gog_artifacts.py``.
    """

    #: Config-file contents keyed by an adapter-defined logical name.
    files: dict[str, str] = field(default_factory=dict)
    #: Environment for the pod Secret. May carry credential material.
    env: dict[str, str] = field(default_factory=dict)
    #: Block appended to AGENTS.md, which both runtimes auto-load.
    policy_md: str = ""


class IntegrationPlugin[ContentT: SecretContent](ABC):
    """One tool-Integration provider: its credential, validation, and egress behavior.

    Generic over the provider's credential model so a plugin's overrides can name their
    concrete content type (``GithubContent``) instead of widening to ``SecretContent``.
    """

    #: Canonical lowercase key. Matches the stored ``SecretProvider`` value.
    key: str
    #: The enum member this plugin owns. Retained while ``SecretProvider`` is still the
    #: persisted column type; the registry checks that ``key`` and ``provider`` agree.
    provider: SecretProvider
    #: Backend-stamped label; never user-entered.
    display_name: str
    schema_version: int = 1
    credentials_model: type[ContentT]
    egress_mode: EgressMode = EgressMode.DIRECT
    #: Which agent-side CLI reaches this provider. Must resolve to a registered adapter.
    runtime_tool: str
    #: Whether an org-scoped Shared Credential may carry this provider. OAuth-based
    #: providers are excluded because their consent is per-agent.
    shared_credential_eligible: bool = False
    #: Bundled skill slugs auto-mounted when this provider is configured.
    bundled_skill_slugs: tuple[str, ...] = ()

    def validate_external(self, content: ContentT) -> IntegrationValidationResult | None:
        """Check the credential against the live provider.

        ``None`` means this provider has no live validator, which keeps it
        schema-validated only — the existing contract for the calendars and Firecrawl.
        """
        del content
        return None

    # --- GATEWAY_PROXY seam ---

    def upstream_base_url(self, content: ContentT) -> str:
        """Absolute base URL the gateway forwards to for this credential."""
        raise NotImplementedError(f"{self.key} is not a {EgressMode.GATEWAY_PROXY.value} provider")

    def apply_upstream_auth(self, content: ContentT, request: OutboundRequest) -> OutboundRequest:
        """Attach the real upstream authorization to a forwarded request.

        A method rather than a declarative scheme table: bearer, basic, custom header,
        query parameter, and request signing all cost the same amount of interface here.
        """
        raise NotImplementedError(f"{self.key} is not a {EgressMode.GATEWAY_PROXY.value} provider")

    # --- TOKEN_BROKER seam ---

    def mint_upstream_token(self, content: ContentT) -> MintedToken:
        """Mint a short-lived upstream token for the agent pod to use directly.

        Synchronous to match ``apply_upstream_auth``, which also performs provider I/O.
        The gateway runs both off the event loop.
        """
        raise NotImplementedError(f"{self.key} is not a {EgressMode.TOKEN_BROKER.value} provider")
