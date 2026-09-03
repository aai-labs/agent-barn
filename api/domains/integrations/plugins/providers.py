"""The shipped Integration Plugins, one class per provider.

``egress_mode`` states what a provider *supports*, not what is switched on: routing a
provider through the gateway additionally requires its key in
``Config.credential_gateway_providers``. That split keeps rollout and rollback a config
change rather than a deploy, and keeps a provider ``DIRECT`` until someone enables it.

Plugins are trusted release artifacts, not dynamically installed packages: adding one is
a merged PR, never runtime registration.
"""

from __future__ import annotations

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
from api.domains.integrations.plugins.base import EgressMode, IntegrationPlugin, OutboundRequest
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
        # Same three headers the live validator sends. Pinning the API version here
        # rather than letting the agent choose keeps one provider contract per plugin.
        return request.with_headers(
            {
                "Authorization": f"Bearer {content.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

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
                'auth_type = "gateway"\n',
                f"base_url = {quote(base_url)}\n",
                f"token_env = {quote(token_env)}\n",
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

    def aai_cli_context_line(self, content: JiraContent) -> str:
        return f"- **Jira** (`{self.aai_cli_slug}`): {content.site_url} ({content.email})"


class ConfluencePlugin(AaiCliPlugin[ConfluenceContent]):
    key = "confluence"
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

    def aai_cli_context_line(self, content: ConfluenceContent) -> str:
        return f"- **Confluence** (`{self.aai_cli_slug}`): {content.site_url} ({content.email})"


class BitbucketPlugin(AaiCliPlugin[BitbucketContent]):
    key = "bitbucket"
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


class ZohoCalendarPlugin(AaiCliPlugin[ZohoCalendarContent]):
    key = "zoho_calendar"
    provider = SecretProvider.ZOHO_CALENDAR
    display_name = "Zoho Calendar credential"
    credentials_model = ZohoCalendarContent
    #: CalDAV rather than REST, and the only aai-cli provider that injects its
    #: credential as plain env (``password_env``) instead of the secret store.
    bundled_skill_slugs = ()

    aai_cli_slug = "zoho-calendar-work"
    aai_cli_label = "Zoho Calendar"

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


class PipedrivePlugin(AaiCliPlugin[PipedriveContent]):
    key = "pipedrive"
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

    def aai_cli_profile_block(self, content: PipedriveContent) -> str:
        lines = [
            f"[profiles.{self.aai_cli_slug}]\n",
            'auth_type = "pipedrive_personal_token"\n',
        ]
        if content.domain:
            lines.append(f"base_url = {quote(f'https://{content.domain}.pipedrive.com')}\n")
        lines.append('api_token_secret = "pipedrive.api_token"\n')
        return "".join(lines)


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
