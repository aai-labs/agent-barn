"""The shipped Integration Plugins, one class per provider.

``egress_mode`` owns how a provider sends credentials. The global gateway switch is an
operational rollback only; it does not duplicate provider registration. Adding a new
gateway provider therefore stays local to its plugin.

Plugins are trusted release artifacts, not dynamically installed packages: adding one is
a merged PR, never runtime registration.
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    FirecrawlContent,
    GithubContent,
    GoogleWorkspaceContent,
    JiraContent,
    PipedriveContent,
    SecretProvider,
    ZohoCalendarContent,
    ZohoMailContent,
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
    OutboundRequest,
    UpstreamAuthenticationError,
)
from api.infrastructure.integration_validators.bitbucket import validate_bitbucket
from api.infrastructure.integration_validators.confluence import validate_confluence
from api.infrastructure.integration_validators.github import validate_github
from api.infrastructure.integration_validators.google_workspace import validate_google_workspace
from api.infrastructure.integration_validators.jira import validate_jira
from api.infrastructure.integration_validators.pipedrive import validate_pipedrive
from api.infrastructure.integration_validators.result import IntegrationValidationResult

AAI_CLI = "aai-cli"
GOG = "gog"
#: Providers reached by no agent-side CLI: the credential is platform infrastructure
#: injected as plain environment.
NO_TOOL = "none"

_ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
_ZOHO_MAIL_BASE_URL = "https://mail.zoho.com"
_ZOHO_CALENDAR_HOSTS = frozenset(
    {
        "calendar.zoho.com",
        "calendar.zoho.eu",
        "calendar.zoho.in",
        "calendar.zoho.com.au",
        "calendar.zoho.jp",
        "calendar.zoho.ca",
        "calendar.zoho.sa",
    }
)
_PIPEDRIVE_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ATLASSIAN_CLOUD_ID = re.compile(r"^[A-Za-z0-9-]+$")


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


def _trusted_zoho_calendar_url(caldav_url: str) -> str:
    parsed = urlsplit(caldav_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or hostname not in _ZOHO_CALENDAR_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Zoho CalDAV URL is not on a supported calendar.zoho host")
    return urlunsplit(("https", hostname, parsed.path, "", ""))


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
            if not content.cloud_id:
                raise ValueError("scoped Jira credential is missing cloud_id")
            return _atlassian_cloud_gateway("jira", content.cloud_id)
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
            if not content.cloud_id:
                return "# jira-work profile skipped: cloud_id missing\n"
            site_url = f"https://api.atlassian.com/ex/jira/{content.cloud_id}"
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
            if not content.cloud_id:
                raise ValueError("scoped Confluence credential is missing cloud_id")
            return _atlassian_cloud_gateway("confluence", content.cloud_id)
        return _atlassian_base(content.site_url)

    def apply_upstream_auth(self, content: ConfluenceContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": _basic_auth(content.email, content.api_token)},
            sensitive=True,
        )

    def aai_cli_profile_block(self, content: ConfluenceContent) -> str:
        site_url = content.site_url
        if content.use_scoped_token:
            if not content.cloud_id:
                return "# confluence-work profile skipped: cloud_id missing\n"
            site_url = f"https://api.atlassian.com/ex/confluence/{content.cloud_id}"
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


class ZohoMailPlugin(AaiCliPlugin[ZohoMailContent]):
    key = "zoho_mail"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.ZOHO_MAIL
    display_name = "Zoho Mail credential"
    credentials_model = ZohoMailContent
    shared_credential_eligible = True
    bundled_skill_slugs = ("aai-zoho-mail",)

    aai_cli_slug = "zoho-mail-rest"
    aai_cli_label = "Zoho Mail"
    aai_cli_capability = "read and search mail (read-only)"
    aai_cli_secret_entries = (
        ("zoho.client_secret", "client_secret"),
        ("zoho.mail_refresh_token", "refresh_token"),
    )

    def __init__(self) -> None:
        self._token_cache: dict[str, tuple[str, float]] = {}
        self._token_cache_lock = threading.Lock()

    def upstream_base_url(self, content: ZohoMailContent) -> str:
        del content
        return _ZOHO_MAIL_BASE_URL

    def apply_upstream_auth(self, content: ZohoMailContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": f"Zoho-oauthtoken {self._access_token(content)}"},
            sensitive=True,
        )

    def _access_token(self, content: ZohoMailContent) -> str:
        cache_key = hashlib.sha256(
            f"{content.client_id}\0{content.client_secret}\0{content.refresh_token}".encode()
        ).hexdigest()
        now = time.monotonic()
        with self._token_cache_lock:
            cached = self._token_cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]

        # Do not hold the cache lock across provider I/O: one tenant's slow refresh
        # must not block another tenant whose credential has a different cache key.
        try:
            response = httpx.post(
                _ZOHO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": content.refresh_token,
                    "client_id": content.client_id,
                    "client_secret": content.client_secret,
                },
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise UpstreamAuthenticationError("Zoho token endpoint could not be reached") from exc
        if response.status_code != 200:
            raise UpstreamAuthenticationError("Zoho rejected the stored OAuth credential")
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamAuthenticationError("Zoho returned an invalid token response") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise UpstreamAuthenticationError("Zoho token response omitted access_token")
        expires_in = payload.get("expires_in_sec", payload.get("expires_in", 3600))
        try:
            ttl = float(expires_in)
        except TypeError, ValueError:
            ttl = 3600.0
        with self._token_cache_lock:
            self._token_cache[cache_key] = (token, now + max(1.0, ttl - 60.0))
        return token

    def aai_cli_profile_block(self, content: ZohoMailContent) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "zoho"\n'
            'auth_type = "zoho_oauth"\n'
            f"email = {quote(content.email)}\n"
            f"account_id = {quote(content.account_id)}\n"
            f"client_id = {quote(content.client_id)}\n"
            'client_secret_secret = "zoho.client_secret"\n'
            'refresh_token_secret = "zoho.mail_refresh_token"\n'
        )

    def aai_cli_gateway_profile_block(self, content: ZohoMailContent, *, base_url: str, token_env: str) -> str:
        return "".join(
            [
                f"[profiles.{self.aai_cli_slug}]\n",
                'provider = "zoho"\n',
                *_gateway_bearer_lines(endpoint_field="base_url", base_url=base_url, token_env=token_env),
                f"email = {quote(content.email)}\n",
                f"account_id = {quote(content.account_id)}\n",
            ]
        )


class ZohoCalendarPlugin(AaiCliPlugin[ZohoCalendarContent]):
    key = "zoho_calendar"
    egress_mode = EgressMode.GATEWAY_PROXY
    provider = SecretProvider.ZOHO_CALENDAR
    display_name = "Zoho Calendar credential"
    credentials_model = ZohoCalendarContent
    #: CalDAV rather than REST, and the only aai-cli provider that injects its
    #: credential as plain env (``password_env``) instead of the secret store.
    bundled_skill_slugs = ()

    aai_cli_slug = "zoho-calendar-work"
    aai_cli_label = "Zoho Calendar"

    def upstream_base_url(self, content: ZohoCalendarContent) -> str:
        return _trusted_zoho_calendar_url(content.caldav_url)

    def apply_upstream_auth(self, content: ZohoCalendarContent, request: OutboundRequest) -> OutboundRequest:
        return request.with_headers(
            {"Authorization": _basic_auth(content.username, content.app_password)},
            sensitive=True,
        )

    def aai_cli_profile_block(self, content: ZohoCalendarContent) -> str:
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "zoho"\n'
            'transport = "caldav"\n'
            'auth_type = "app_password"\n'
            f"username = {quote(content.username)}\n"
            f"email = {quote(content.email)}\n"
            'password_env = "ZOHO_CALENDAR_APP_PASSWORD"\n'
            f"caldav_url = {quote(content.caldav_url)}\n"
        )

    def aai_cli_gateway_profile_block(self, content: ZohoCalendarContent, *, base_url: str, token_env: str) -> str:
        # CalDAV has its own aai-cli transport and always emits Basic auth. Supplying
        # the Gateway Token as its password preserves that existing CLI contract; the
        # gateway extracts the password and replaces the entire Authorization header.
        return (
            f"[profiles.{self.aai_cli_slug}]\n"
            'provider = "zoho"\n'
            'transport = "caldav"\n'
            'auth_type = "app_password"\n'
            f"username = {quote(content.username)}\n"
            f"email = {quote(content.email)}\n"
            f"password_env = {quote(token_env)}\n"
            f"caldav_url = {quote(base_url)}\n"
        )


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


class GoogleWorkspacePlugin(IntegrationPlugin[GoogleWorkspaceContent]):
    """Google Workspace, reached by gog rather than aai-cli.

    Deliberately not an ``AaiCliIntegration``: gog takes no ``--profile``, shares none of
    aai-cli's secret-store machinery, and carries its own agents_md policy block.
    """

    key = "google_workspace"
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


class FirecrawlPlugin(IntegrationPlugin[FirecrawlContent]):
    """Infrastructure-level web fetch/search, injected as plain environment.

    Reached by no agent-side CLI, so it has no adapter behavior beyond its env.
    """

    key = "firecrawl"
    provider = SecretProvider.FIRECRAWL
    display_name = "Firecrawl credential"
    credentials_model = FirecrawlContent
    runtime_tool = NO_TOOL
    bundled_skill_slugs = ()


SHIPPED_PLUGINS: tuple[IntegrationPlugin, ...] = (
    GithubPlugin(),
    JiraPlugin(),
    ConfluencePlugin(),
    BitbucketPlugin(),
    ZohoMailPlugin(),
    ZohoCalendarPlugin(),
    FirecrawlPlugin(),
    PipedrivePlugin(),
    GoogleWorkspacePlugin(),
)
