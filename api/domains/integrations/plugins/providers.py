"""The shipped Integration Plugins, one class per provider.

``egress_mode`` declares the available isolated route. Stored per-binding policy
selects it or the direct adapter. Durable token rotation uses a broker service.

Plugins are trusted release artifacts, not dynamically installed packages: adding one is
a merged PR, never runtime registration.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from dataclasses import asdict
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from api.domains.agents.microsoft_graph_scopes import GRAPH_SCOPE_PREFIX, sharepoint_permission
from api.domains.agents.models import (
    ApolloContent,
    BitbucketContent,
    ConfluenceContent,
    FirecrawlContent,
    GithubContent,
    GmailAppPasswordContent,
    GmailContent,
    GoogleWorkspaceContent,
    JiraContent,
    MerkysContent,
    PipedriveContent,
    SecretProvider,
    SharePointContent,
)
from api.domains.integrations.plugins.aai_cli_support import (
    AaiCliPlugin,
    profile_repo_pairs,
    quote,
    repo_scoped_profile_line,
)
from api.domains.integrations.plugins.base import (
    EgressMode,
    IntegrationPlugin,
    MintedToken,
    OutboundRequest,
    ServedRequest,
    ServedResponse,
    TokenBrokerService,
    UpstreamAuthenticationError,
)
from api.infrastructure.google.gmail_imap import (
    MAX_LIST_LIMIT,
    GmailInbox,
    InvalidMailQuery,
    MailNotFound,
    MailSignInFailed,
    MailUnavailable,
)
from api.infrastructure.integration_validators.apollo import validate_apollo
from api.infrastructure.integration_validators.bitbucket import validate_bitbucket
from api.infrastructure.integration_validators.confluence import validate_confluence
from api.infrastructure.integration_validators.github import validate_github
from api.infrastructure.integration_validators.gmail import validate_gmail
from api.infrastructure.integration_validators.gmail_app_password import validate_gmail_app_password
from api.infrastructure.integration_validators.google_workspace import validate_google_workspace
from api.infrastructure.integration_validators.jira import validate_jira
from api.infrastructure.integration_validators.merkys import validate_merkys
from api.infrastructure.integration_validators.pipedrive import validate_pipedrive
from api.infrastructure.integration_validators.result import IntegrationValidationResult

AAI_CLI = "aai-cli"
GOG = "gog"
#: Providers reached by no agent-side CLI: the credential is platform infrastructure
#: injected as plain environment.
NO_TOOL = "none"
#: The address an agent's aai-cli Custom API profile uses for Gmail read with an app
#: password. A label only: aai-cli posts the request to the credential gateway and never
#: contacts this host, and the gateway answers it from IMAP.
GMAIL_SERVED_BASE_URL = "https://gmail.internal/v1"
_GMAIL_MESSAGE_PATH = re.compile(r"/v1/messages/([0-9]{1,20})")
_GMAIL_LIMIT = re.compile(r"[0-9]{1,3}")
_GMAIL_DEFAULT_LIMIT = 20

_PIPEDRIVE_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_ATLASSIAN_CLOUD_ID = re.compile(r"^[A-Za-z0-9-]+$")
#: Hosts the credential gateway may forward a Merkys key to. A Merkys base URL is entered
#: by the user, so without this list the gateway would send the key to any https host a
#: user typed. Other deployments (on-prem) keep working in direct mode, where the key goes
#: to the agent's own aai-cli rather than through a shared service.
_MERKYS_GATEWAY_HOST_SUFFIXES = (".aai-labs.com",)


def _basic_auth(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def _gateway_bearer_lines(*, endpoint_field: str, base_url: str, token_env: str) -> list[str]:
    """Existing aai-cli fields for the pod-to-gateway HTTP hop."""
    return [
        'auth_type = "bearer_token"\n',
        f"{endpoint_field} = {quote(base_url)}\n",
        f"token_env = {quote(token_env)}\n",
    ]


def _atlassian_base(site_url: str) -> str:
    """Return a tenant origin while preventing stored URLs from turning into SSRF."""
    parsed = urlsplit(site_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".atlassian.net")
        or hostname == ".atlassian.net"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Atlassian site URL must be an https *.atlassian.net origin")
    return urlunsplit(("https", hostname, "", "", ""))


def _atlassian_cloud_gateway(service: str, cloud_id: str) -> str:
    if service not in {"jira", "confluence"} or not _ATLASSIAN_CLOUD_ID.fullmatch(cloud_id):
        raise ValueError("Atlassian cloud_id is not valid")
    return f"https://api.atlassian.com/ex/{service}/{cloud_id}"


def _atlassian_scoped_gateway_url(service: str, cloud_id: str | None) -> str | None:
    """Resolve the API Gateway URL for a scoped Jira/Confluence token, or None if unusable."""
    return _atlassian_cloud_gateway(service, cloud_id) if cloud_id else None


class GithubPlugin(AaiCliPlugin[GithubContent]):
    key = "github"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.GITHUB
    display_name = "GitHub credential"
    credentials_model = GithubContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-github",)

    aai_cli_slug = "github-work"
    aai_cli_label = "GitHub"
    aai_cli_capability = "PRs (diff, files, reviews, comments), issues, branches, repo source, Actions runs"
    aai_cli_secret_entries = (("github.token", "token"),)

    def validate_external(self, content: GithubContent) -> IntegrationValidationResult:
        return validate_github(content)

    def upstream_base_url(self, content: GithubContent) -> str:
        del content
        return "https://api.github.com"

    def apply_upstream_auth(self, content: GithubContent, request: OutboundRequest) -> OutboundRequest:
        headers = {
            "Authorization": f"Bearer {content.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Preserve aai-cli's media-type requests for diffs, raw files, and archive
        # downloads. Ordinary JSON requests receive the same default as validation.
        accept = next((value for name, value in request.headers.items() if name.lower() == "accept"), None)
        if accept in {None, "*/*"}:
            headers["Accept"] = "application/vnd.github+json"
        return request.with_headers(headers, sensitive=True)

    def aai_cli_profile_block(self, content: GithubContent) -> str:
        blocks = []
        for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos):
            lines = [
                f"[profiles.{name}]\n",
                'provider = "github"\n',
                'auth_type = "bearer_token"\n',
                'token_secret = "github.token"\n',
                f"owner = {quote(content.owner)}\n",
            ]
            if repo is not None:
                lines.append(f"repo = {quote(repo)}\n")
            lines.append(f"org = {quote(content.org)}\n")
            blocks.append("".join(lines))
        return "\n".join(blocks)

    def aai_cli_gateway_profile_block(self, content: GithubContent, *, base_url: str, token_env: str) -> str:
        blocks = []
        for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos):
            lines = [
                f"[profiles.{name}]\n",
                'provider = "github"\n',
                *_gateway_bearer_lines(endpoint_field="base_url", base_url=base_url, token_env=token_env),
                f"owner = {quote(content.owner)}\n",
            ]
            if repo is not None:
                lines.append(f"repo = {quote(repo)}\n")
            lines.append(f"org = {quote(content.org)}\n")
            blocks.append("".join(lines))
        return "\n".join(blocks)

    def aai_cli_context_line(self, content: GithubContent) -> str:
        if content.repos:
            pairs = "; ".join(
                f"`{name}`: {content.owner}/{repo}"
                for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos)
            )
            return f"- **GitHub**: {pairs}"
        return (
            f"- **GitHub** (`{self.aai_cli_slug}`): owner/org `{content.owner}` — "
            "no repository configured; pass --repo explicitly"
        )

    def aai_cli_policy_line(self, content: GithubContent) -> str:
        return repo_scoped_profile_line("GitHub", self.aai_cli_slug, content.owner, "owner", content.repos)


class JiraPlugin(AaiCliPlugin[JiraContent]):
    key = "jira"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.JIRA
    display_name = "Jira credential"
    credentials_model = JiraContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-jira",)

    aai_cli_slug = "jira-work"
    aai_cli_label = "Jira"
    aai_cli_capability = "issues (comments, attachments), sprints, boards, projects, users"
    aai_cli_secret_entries = (("jira.api_token", "api_token"),)

    def validate_external(self, content: JiraContent) -> IntegrationValidationResult:
        return validate_jira(content)

    def upstream_base_url(self, content: JiraContent) -> str:
        if content.use_scoped_token:
            url = _atlassian_scoped_gateway_url("jira", content.cloud_id)
            if url is None:
                raise ValueError("scoped Jira credential is missing cloud_id")
            return url
        return _atlassian_base(content.site_url)

    def apply_upstream_auth(self, content: JiraContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": _basic_auth(content.email, content.api_token)},
            sensitive=True,
        )

    def aai_cli_profile_block(self, content: JiraContent) -> str:
        site_url = content.site_url
        if content.use_scoped_token:
            # Scoped tokens are still Basic Auth, but must go through the API Gateway
            # (keyed by cloud_id) rather than the site URL directly.
            # If cloud_id is missing, skip the profile — the user must re-save the integration.
            scoped_url = _atlassian_scoped_gateway_url("jira", content.cloud_id)
            if scoped_url is None:
                return "# jira-work profile skipped: cloud_id missing\n"
            site_url = scoped_url
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'auth_type = "basic_api_token"\n'
            f"site_url = {quote(site_url)}\n"
            f"email = {quote(content.email)}\n"
            'api_token_secret = "jira.api_token"\n'
        )

    def aai_cli_gateway_profile_block(self, content: JiraContent, *, base_url: str, token_env: str) -> str:
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                *_gateway_bearer_lines(endpoint_field="site_url", base_url=base_url, token_env=token_env),
                f"email = {quote(content.email)}\n",
            ]
        )

    def aai_cli_context_line(self, content: JiraContent) -> str:
        return f"- **Jira** (`{self.aai_cli_slug}`): {content.site_url} ({content.email})"


class ConfluencePlugin(AaiCliPlugin[ConfluenceContent]):
    key = "confluence"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.CONFLUENCE
    display_name = "Confluence credential"
    credentials_model = ConfluenceContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-confluence",)

    aai_cli_slug = "confluence-work"
    aai_cli_label = "Confluence"
    aai_cli_capability = "pages (comments, attachments), spaces"
    aai_cli_secret_entries = (("confluence.api_token", "api_token"),)

    def validate_external(self, content: ConfluenceContent) -> IntegrationValidationResult:
        return validate_confluence(content)

    def upstream_base_url(self, content: ConfluenceContent) -> str:
        if content.use_scoped_token:
            url = _atlassian_scoped_gateway_url("confluence", content.cloud_id)
            if url is None:
                raise ValueError("scoped Confluence credential is missing cloud_id")
            return url
        return _atlassian_base(content.site_url)

    def apply_upstream_auth(self, content: ConfluenceContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": _basic_auth(content.email, content.api_token)},
            sensitive=True,
        )

    def aai_cli_profile_block(self, content: ConfluenceContent) -> str:
        site_url = content.site_url
        if content.use_scoped_token:
            scoped_url = _atlassian_scoped_gateway_url("confluence", content.cloud_id)
            if scoped_url is None:
                return "# confluence-work profile skipped: cloud_id missing\n"
            site_url = scoped_url
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'auth_type = "basic_api_token"\n'
            f"site_url = {quote(site_url)}\n"
            f"email = {quote(content.email)}\n"
            'api_token_secret = "confluence.api_token"\n'
        )

    def aai_cli_gateway_profile_block(self, content: ConfluenceContent, *, base_url: str, token_env: str) -> str:
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                *_gateway_bearer_lines(endpoint_field="site_url", base_url=base_url, token_env=token_env),
                f"email = {quote(content.email)}\n",
            ]
        )

    def aai_cli_context_line(self, content: ConfluenceContent) -> str:
        return f"- **Confluence** (`{self.aai_cli_slug}`): {content.site_url} ({content.email})"


class BitbucketPlugin(AaiCliPlugin[BitbucketContent]):
    key = "bitbucket"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.BITBUCKET
    display_name = "Bitbucket credential"
    credentials_model = BitbucketContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-bitbucket",)

    aai_cli_slug = "bitbucket-work"
    aai_cli_label = "Bitbucket"
    aai_cli_capability = "PRs (diff, comments), commits, branches, repo source, pipelines"
    aai_cli_secret_entries = (("bitbucket.api_token", "api_token"),)

    def validate_external(self, content: BitbucketContent) -> IntegrationValidationResult:
        return validate_bitbucket(content)

    def upstream_base_url(self, content: BitbucketContent) -> str:
        del content
        return "https://api.bitbucket.org/2.0"

    def apply_upstream_auth(self, content: BitbucketContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": _basic_auth(content.email, content.api_token)},
            sensitive=True,
        )

    def aai_cli_profile_block(self, content: BitbucketContent) -> str:
        blocks = []
        for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos):
            lines = [
                f"[profiles.{name}]\n",
                'auth_type = "basic_api_token"\n',
                f"workspace = {quote(content.workspace)}\n",
            ]
            if repo is not None:
                lines.append(f"repo = {quote(repo)}\n")
            lines.append(f"email = {quote(content.email)}\n")
            lines.append('api_token_secret = "bitbucket.api_token"\n')
            blocks.append("".join(lines))
        return "\n".join(blocks)

    def aai_cli_gateway_profile_block(self, content: BitbucketContent, *, base_url: str, token_env: str) -> str:
        blocks = []
        for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos):
            lines = [
                f"[profiles.{name}]\n",
                *_gateway_bearer_lines(endpoint_field="base_url", base_url=base_url, token_env=token_env),
                f"workspace = {quote(content.workspace)}\n",
            ]
            if repo is not None:
                lines.append(f"repo = {quote(repo)}\n")
            lines.append(f"email = {quote(content.email)}\n")
            blocks.append("".join(lines))
        return "\n".join(blocks)

    def aai_cli_context_line(self, content: BitbucketContent) -> str:
        if content.repos:
            pairs = "; ".join(
                f"`{name}`: {content.workspace}/{repo}"
                for name, repo in profile_repo_pairs(self.aai_cli_slug, content.repos)
            )
            return f"- **Bitbucket**: {pairs} ({content.email})"
        return (
            f"- **Bitbucket** (`{self.aai_cli_slug}`): workspace `{content.workspace}` "
            f"({content.email}) — no repository configured; pass --repo explicitly"
        )

    def aai_cli_policy_line(self, content: BitbucketContent) -> str:
        return repo_scoped_profile_line("Bitbucket", self.aai_cli_slug, content.workspace, "workspace", content.repos)


class PipedrivePlugin(AaiCliPlugin[PipedriveContent]):
    key = "pipedrive"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.PIPEDRIVE
    display_name = "Pipedrive credential"
    credentials_model = PipedriveContent
    bundled_skill_slugs = ("aai-pipedrive",)

    aai_cli_slug = "pipedrive-work"
    aai_cli_label = "Pipedrive"
    aai_cli_capability = "deals, leads, persons, organizations, activities, notes, mailbox"
    aai_cli_secret_entries = (("pipedrive.api_token", "api_token"),)

    def validate_external(self, content: PipedriveContent) -> IntegrationValidationResult:
        return validate_pipedrive(content)

    def upstream_base_url(self, content: PipedriveContent) -> str:
        if not content.domain:
            return "https://api.pipedrive.com"
        domain = content.domain.lower()
        if not _PIPEDRIVE_DOMAIN.fullmatch(domain):
            raise ValueError("Pipedrive domain is not a valid tenant subdomain")
        return f"https://{domain}.pipedrive.com"

    def apply_upstream_auth(self, content: PipedriveContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers({"x-api-token": content.api_token}, sensitive=True)

    def aai_cli_profile_block(self, content: PipedriveContent) -> str:
        lines = [
            f"[profiles.{self.aai_cli_slug}]\n",
            'auth_type = "pipedrive_personal_token"\n',
        ]
        if content.domain:
            lines.append(f"base_url = {quote(f'https://{content.domain}.pipedrive.com')}\n")
        lines.append('api_token_secret = "pipedrive.api_token"\n')
        return "".join(lines)

    def aai_cli_gateway_profile_block(self, content: PipedriveContent, *, base_url: str, token_env: str) -> str:
        del content
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                *_gateway_bearer_lines(endpoint_field="base_url", base_url=base_url, token_env=token_env),
            ]
        )


class ApolloPlugin(AaiCliPlugin[ApolloContent]):
    key = "apollo"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.APOLLO
    display_name = "Apollo credential"
    credentials_model = ApolloContent
    bundled_skill_slugs = ("aai-apollo",)
    aai_cli_slug = "apollo-work"
    aai_cli_label = "Apollo"
    aai_cli_capability = (
        "people and organization search and enrichment, contacts, accounts, deals, sequences, "
        "emails, tasks, calls, notes; a key reaches only the endpoints chosen when it was "
        "created, and people and organization search and enrichment need a paid Apollo plan, "
        "so a 403 means the key or plan lacks access to that endpoint, not that Apollo is unavailable"
    )
    aai_cli_secret_entries = (("apollo.api_token", "api_token"),)

    def validate_external(self, content: ApolloContent) -> IntegrationValidationResult:
        return validate_apollo(content)

    def upstream_base_url(self, content: ApolloContent) -> str:
        # Typed API and health endpoints have different version prefixes.
        return "https://api.apollo.io"

    def apply_upstream_auth(self, content: ApolloContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers({"x-api-key": content.api_token}, sensitive=True)

    def aai_cli_gateway_profile_block(self, content: ApolloContent, *, base_url: str, token_env: str) -> str:
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                'provider = "apollo"\n',
                *_gateway_bearer_lines(
                    endpoint_field="base_url", base_url=base_url.rstrip("/") + "/api/v1", token_env=token_env
                ),
            ]
        )

    def aai_cli_profile_block(self, content: ApolloContent) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "apollo"\n'
            'auth_type = "apollo_api_key"\n'
            'api_token_secret = "apollo.api_token"\n'
        )


def _merkys_gateway_origin(base_url: str) -> str:
    """Return the Merkys origin the gateway may forward to, or raise ``ValueError``."""
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not any(
            hostname.endswith(suffix) and hostname != suffix.lstrip(".") for suffix in _MERKYS_GATEWAY_HOST_SUFFIXES
        )
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Merkys isolated mode needs an https URL on an Agent Barn–approved host")
    return urlunsplit(("https", hostname, "", "", ""))


class MerkysPlugin(AaiCliPlugin[MerkysContent]):
    key = "merkys"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.MERKYS
    display_name = "Merkys credential"
    credentials_model = MerkysContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-merkys",)
    upstream_timeout_seconds = 90
    max_concurrent_upstream = 8

    aai_cli_slug = "merkys-work"
    aai_cli_label = "Merkys"
    aai_cli_capability = (
        "ask questions of the organization's knowledge base and get answers with cited sources, "
        "run deep research, list conversations, documents and data sources; "
        "calls run as the API key's owner, so a 403 or an empty list can mean that user lacks access"
    )
    aai_cli_secret_entries = (("merkys.api_key", "api_key"),)

    def validate_external(self, content: MerkysContent) -> IntegrationValidationResult:
        return validate_merkys(content)

    def upstream_base_url(self, content: MerkysContent) -> str:
        return _merkys_gateway_origin(content.base_url)

    def validate_direct_content(self, content: MerkysContent) -> None:
        # The gateway allowlist does not apply to direct mode: the key goes from the agent's
        # own aai-cli to the URL the model already reduced to an https origin, which is how
        # an on-prem Merkys is reached.
        del content

    def apply_upstream_auth(self, content: MerkysContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers({"X-API-Key": content.api_key}, sensitive=True)

    def aai_cli_profile_block(self, content: MerkysContent) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "merkys"\n'
            'auth_type = "api_key_header"\n'
            f"base_url = {quote(content.base_url)}\n"
            'api_token_secret = "merkys.api_key"\n'
        )

    def aai_cli_gateway_profile_block(self, content: MerkysContent, *, base_url: str, token_env: str) -> str:
        # Checked here too so that switching an agent to isolated mode fails in the apply
        # preflight, not later when the pod's first request is refused at the gateway.
        _merkys_gateway_origin(content.base_url)
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                'provider = "merkys"\n',
                *_gateway_bearer_lines(endpoint_field="base_url", base_url=base_url, token_env=token_env),
            ]
        )

    def aai_cli_context_line(self, content: MerkysContent) -> str:
        return f"- **Merkys** (`{self.aai_cli_slug}`): {content.base_url}"


class GoogleWorkspacePlugin(IntegrationPlugin[GoogleWorkspaceContent]):
    """Google Workspace, reached by gog rather than aai-cli.

    Deliberately not an ``AaiCliIntegration``: gog takes no ``--profile``, shares none of
    aai-cli's secret-store machinery, and carries its own agents_md policy block.
    """

    key = "google_workspace"
    egress_mode = EgressMode.TOKEN_BROKER
    provider = SecretProvider.GOOGLE_WORKSPACE
    display_name = "Google Workspace credential"
    credentials_model = GoogleWorkspaceContent
    runtime_tool = GOG
    #: OAuth-based, so its consent is per-agent and it cannot be an org-scoped
    #: Shared Credential.
    shared_credential_eligible = False
    bundled_skill_slugs = ()

    def validate_external(self, content: GoogleWorkspaceContent) -> IntegrationValidationResult:
        return validate_google_workspace(content)

    def mint_upstream_token(self, content: GoogleWorkspaceContent) -> MintedToken:
        """Exchange the stored refresh token for a short-lived Google access token.

        Brokered rather than proxied because gog exposes no base-URL override but does
        accept a pre-minted token, so the pod can be handed an expiring credential
        without any gog change. The refresh token and OAuth client secret — the
        renewable half of the grant — stay here.

        Not cached: each mint is one request per agent process start, not per API call,
        and a cache keyed on the credential would hold live Google tokens in gateway
        memory for an hour with no way to drop them on revocation.
        """
        if not content.client_id or not content.client_secret:
            raise UpstreamAuthenticationError("Google OAuth client is not configured for this credential")
        try:
            response = httpx.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": content.refresh_token,
                    "client_id": content.client_id,
                    "client_secret": content.client_secret,
                },
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise UpstreamAuthenticationError("Google token endpoint could not be reached") from exc
        if response.status_code != 200:
            raise UpstreamAuthenticationError("Google rejected the stored OAuth credential")
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamAuthenticationError("Google returned an invalid token response") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise UpstreamAuthenticationError("Google token response omitted access_token")
        try:
            expires_in = int(payload.get("expires_in", 3600))
        except TypeError, ValueError:
            expires_in = 3600
        # Report the granted scopes rather than the stored ones: a user can trim the
        # grant at myaccount.google.com after consent, and the pod should see what it
        # actually has.
        granted = payload.get("scope", "")
        scopes = frozenset(granted.split()) if granted else frozenset(content.scopes)
        return MintedToken(value=token, expires_in=max(1, expires_in), scopes=scopes)


class GmailPlugin(AaiCliPlugin[GmailContent]):
    """Read-only Gmail through aai-cli's ``email`` commands.

    Separate from Google Workspace (gog): one grant, Gmail only, always read-only, so
    connecting it is a single sign-in on the deployment's shared Google client. Direct
    only — the refresh token and client secret go into aai-cli's encrypted store, which
    refreshes access tokens itself.
    """

    key = "gmail"
    provider = SecretProvider.GMAIL
    display_name = "Gmail credential"
    credentials_model = GmailContent
    #: OAuth-based, so its consent is per-agent and it cannot be an org-scoped
    #: Shared Credential.
    shared_credential_eligible = False
    bundled_skill_slugs = ("aai-gmail",)
    aai_cli_slug = "gmail-work"
    aai_cli_label = "Gmail"
    aai_cli_capability = (
        "list, read and search mail (read-only; sending and deleting are refused) — read `./skills/aai-gmail/SKILL.md`"
    )
    aai_cli_secret_entries = (
        ("google.gmail_client_secret", "client_secret"),
        ("google.gmail_refresh_token", "refresh_token"),
    )

    def validate_external(self, content: GmailContent) -> IntegrationValidationResult:
        return validate_gmail(content)

    def aai_cli_profile_block(self, content: GmailContent) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "google"\n'
            'auth_type = "bearer_token"\n'
            f"client_id = {quote(content.client_id)}\n"
            'client_secret_secret = "google.gmail_client_secret"\n'
            'refresh_token_secret = "google.gmail_refresh_token"\n'
            'user_id = "me"\n'
        )

    def aai_cli_context_line(self, content: GmailContent) -> str:
        return f"- **Gmail** (`{self.aai_cli_slug}`): signed in as {content.email} (read-only)"


class FirecrawlPlugin(IntegrationPlugin[FirecrawlContent]):
    """Infrastructure-level web fetch/search, reached by the pod's built-in web backend
    and the openclaw firecrawl plugin rather than any CLI.

    ``FirecrawlContent.base_url`` (a self-hosted override) is not honored here on
    purpose: the same actor who can set it could otherwise redirect the shared platform
    API key to a host they control, since unlike Jira/Confluence there is no fixed
    tenant suffix to constrain it to. Upstream is pinned to the managed API.
    """

    key = "firecrawl"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.FIRECRAWL
    display_name = "Firecrawl credential"
    credentials_model = FirecrawlContent
    runtime_tool = NO_TOOL
    bundled_skill_slugs = ()

    def upstream_base_url(self, content: FirecrawlContent) -> str:
        del content
        return "https://api.firecrawl.dev"

    def apply_upstream_auth(self, content: FirecrawlContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers({"Authorization": f"Bearer {content.api_key}"}, sensitive=True)


class SharePointPlugin(AaiCliPlugin[SharePointContent]):
    """Delegated SharePoint, with either PVC rotation or service-side token brokerage."""

    key = "sharepoint"
    provider = SecretProvider.SHAREPOINT
    display_name = "SharePoint credential"
    credentials_model = SharePointContent
    egress_mode = EgressMode.TOKEN_BROKER
    bundled_skill_slugs = ("aai-microsoft",)
    token_broker_service = TokenBrokerService.SHAREPOINT
    aai_cli_slug = "sharepoint-work"
    aai_cli_label = "SharePoint"
    aai_cli_secret_entries = (("microsoft.sharepoint_refresh_token", "refresh_token"),)
    aai_cli_capability = (
        "SharePoint only, as the signed-in account: files in document libraries "
        "(`microsoft sharepoint files` upload/download/delete), lists and list items; find sites, "
        "libraries and folders with `microsoft request get` — read `./skills/aai-microsoft/SKILL.md`"
    )

    def aai_cli_selected_sites_profile_block(self, token_url: str | None) -> str:
        if not token_url:
            raise ValueError("Selected-sites SharePoint requires its platform token URL")
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "microsoft"\n'
            'auth_type = "token_url"\n'
            f"token_url = {quote(token_url)}\n"
            'api_token_secret = "agentfarm.ingest_key"\n'
        )

    def aai_cli_capability_for(self, content: SharePointContent) -> str:
        if content.mode == "selected_sites":
            return (
                "SharePoint, the granted sites only: files in their document libraries "
                "(`microsoft sharepoint files` upload/download/delete), lists and list items; "
                "find libraries and folders with `microsoft request get` — read `./skills/aai-microsoft/SKILL.md`"
            )
        return self.aai_cli_capability

    def aai_cli_profile_block(self, content: SharePointContent) -> str:
        scope = f"{GRAPH_SCOPE_PREFIX}{sharepoint_permission(content.read_only)} offline_access"
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "microsoft"\n'
            'auth_type = "microsoft_delegated"\n'
            f"tenant_id = {quote(content.tenant_id)}\n"
            f"client_id = {quote(content.client_id)}\n"
            f"scope = {quote(scope)}\n"
            'refresh_token_secret = "microsoft.sharepoint_refresh_token"\n'
        )

    def aai_cli_gateway_profile_block(self, content: SharePointContent, *, base_url: str, token_env: str) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "microsoft"\n'
            'auth_type = "token_url"\n'
            f"token_url = {quote(base_url)}\n"
            f"api_token_env = {quote(token_env)}\n"
        )

    def aai_cli_context_line(self, content: SharePointContent) -> str:
        access = "read-only" if content.read_only else "read and write"
        if content.mode == "selected_sites":
            sites = ", ".join(site.url for site in content.sites)
            return (
                f"- **SharePoint** (`{self.aai_cli_slug}`): only these sites ({access}): {sites}. "
                "Anything else is refused. Excel workbook commands aren't available here; "
                "download, edit and upload the file instead"
            )
        return (
            f"- **SharePoint** (`{self.aai_cli_slug}`): signed in as {content.email} ({access}) — SharePoint only: "
            "the sites, libraries and files that account can open; Outlook, Teams messages, To Do and "
            "Planner aren't authorised"
        )


class GmailAppPasswordPlugin(AaiCliPlugin[GmailAppPasswordContent]):
    """Gmail read over IMAP by the credential gateway with a Google app password.

    An app password cannot be limited to reading, so it is gateway-served only: the
    agent's aai-cli posts Custom API requests to the gateway, which signs in and reads on
    its behalf, and the pod never holds the password. ``serve`` answers exactly two
    requests and refuses everything else before Gmail is contacted; ``GmailInbox`` opens
    the inbox read-only and never marks mail read.
    """

    key = "gmail_app_password"
    egress_mode = EgressMode.GATEWAY_SERVED
    provider = SecretProvider.GMAIL_APP_PASSWORD
    display_name = "Gmail app password"
    credentials_model = GmailAppPasswordContent
    aai_cli_slug = "gmail-inbox"
    aai_cli_label = "Gmail (app password)"
    aai_cli_capability = (
        "read-only inbox. List: `aai-cli --profile gmail-inbox custom-api request --method GET "
        f"--url {GMAIL_SERVED_BASE_URL}/messages` (optionally `--query q=<Gmail search>` and "
        f"`--query limit=<1-{MAX_LIST_LIMIT}>`). Read one: `aai-cli --profile gmail-inbox custom-api request "
        f"--method GET --url {GMAIL_SERVED_BASE_URL}/messages/<id>` with an id from the list. Results are "
        "`{status, body}`; sending, deleting and marking mail read are refused"
    )
    inbox = GmailInbox()

    def validate_external(self, content: GmailAppPasswordContent) -> IntegrationValidationResult:
        return validate_gmail_app_password(content)

    def aai_cli_gateway_profile_block(self, content: GmailAppPasswordContent, *, base_url: str, token_env: str) -> str:
        """An isolated ``custom_api`` profile: no credential, only the gateway and its token."""
        del content
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "custom_api"\n'
            f"base_url = {quote(GMAIL_SERVED_BASE_URL)}\n"
            f"gateway_url = {quote(base_url)}\n"
            f"gateway_token_env = {quote(token_env)}\n"
        )

    def aai_cli_context_line(self, content: GmailAppPasswordContent) -> str:
        return f"- **Gmail** (`{self.aai_cli_slug}`): inbox of {content.email} (read-only)"

    def serve(self, content: GmailAppPasswordContent, request: ServedRequest) -> ServedResponse:
        if request.method.upper() != "GET":
            return _served_error(405, "read_only", "Gmail is read-only here. Only GET requests are accepted.")
        target = urlsplit(request.url)
        base = urlsplit(GMAIL_SERVED_BASE_URL)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc) or target.fragment:
            return _GMAIL_NOT_FOUND
        if request.body is not None:
            return _served_error(400, "invalid_request", "A request body is not accepted.")
        query: dict[str, object] = {
            key: values[0] if len(values) == 1 else values for key, values in parse_qs(target.query).items()
        }
        query.update(request.query)
        if target.path == "/v1/messages":
            return self._list(content, query)
        message = _GMAIL_MESSAGE_PATH.fullmatch(target.path)
        if message is None:
            return _GMAIL_NOT_FOUND
        if query:
            return _served_error(400, "invalid_request", "Reading one message takes no query.")
        return _read_mail(lambda: asdict(self.inbox.get_message(content.email, content.app_password, message[1])))

    def _list(self, content: GmailAppPasswordContent, query: dict[str, object]) -> ServedResponse:
        if set(query) - {"q", "limit"}:
            return _served_error(400, "invalid_request", "Only the q and limit queries are accepted.")
        search = query.get("q")
        raw_limit = query.get("limit", _GMAIL_DEFAULT_LIMIT)
        if search is not None and not isinstance(search, str):
            return _served_error(400, "invalid_request", "q must be one Gmail search.")
        if isinstance(raw_limit, int) and not isinstance(raw_limit, bool):
            limit = raw_limit
        elif isinstance(raw_limit, str) and _GMAIL_LIMIT.fullmatch(raw_limit):
            limit = int(raw_limit)
        else:
            limit = 0
        if not 1 <= limit <= MAX_LIST_LIMIT:
            return _served_error(400, "invalid_request", f"limit must be a whole number from 1 to {MAX_LIST_LIMIT}.")
        return _read_mail(
            lambda: {
                "messages": [
                    asdict(m)
                    for m in self.inbox.list_messages(content.email, content.app_password, query=search, limit=limit)
                ]
            }
        )


def _served_error(status: int, error: str, message: str) -> ServedResponse:
    return ServedResponse(status, {"error": error, "message": message})


_GMAIL_NOT_FOUND = _served_error(
    404, "not_found", f"Only {GMAIL_SERVED_BASE_URL}/messages and {GMAIL_SERVED_BASE_URL}/messages/<id> exist."
)


def _read_mail(read: Callable[[], object]) -> ServedResponse:
    """Run one inbox read, mapping Gmail failures to a status the agent can act on."""
    try:
        return ServedResponse(200, read())
    except InvalidMailQuery:
        return _served_error(400, "invalid_query", "That search cannot be used.")
    except MailNotFound:
        return _served_error(404, "not_found", "No inbox message with that id.")
    except MailSignInFailed:
        return _served_error(
            502, "mail_sign_in_failed", "Gmail rejected the app password. Ask the owner to reconnect Gmail."
        )
    except MailUnavailable:
        return _served_error(502, "upstream_unreachable", "Gmail could not be reached.")


SHIPPED_PLUGINS: tuple[IntegrationPlugin, ...] = (
    GithubPlugin(),
    JiraPlugin(),
    ConfluencePlugin(),
    BitbucketPlugin(),
    FirecrawlPlugin(),
    PipedrivePlugin(),
    ApolloPlugin(),
    MerkysPlugin(),
    GoogleWorkspacePlugin(),
    GmailPlugin(),
    GmailAppPasswordPlugin(),
    SharePointPlugin(),
)
