"""aai-cli-specific plugin surface.

``IntegrationPlugin`` stays tool-neutral, so everything aai-cli needs from a provider —
profile slug, config.toml block, secret-store entries, and the two agents_md lines —
lives on this mixin instead of the base class. A provider on a different CLI implements
that CLI's mixin and never sees any of this.

The registry checks that every plugin whose ``runtime_tool`` is ``aai-cli`` implements
``AaiCliIntegration``.
"""

from __future__ import annotations

from api.domains.agents.models import SecretContent
from api.domains.integrations.plugins.base import IntegrationPlugin

#: Config dir per runtime home. OpenClaw runs as the node user, Hermes as hermes.
SECRETS_SUBDIR = ".config/aai-cli"


def secrets_dir(home_dir: str) -> str:
    return f"{home_dir}/{SECRETS_SUBDIR}"


def env_var_for(secret_name: str) -> str:
    """``"jira.api_token"`` -> ``"AAI_SECRET_JIRA_API_TOKEN"``."""
    return "AAI_SECRET_" + secret_name.upper().replace(".", "_")


def quote(value: str) -> str:
    """TOML-quote a string value, escaping backslashes and double quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def profile_repo_pairs(base_name: str, repos: list[str]) -> list[tuple[str, str | None]]:
    """Map a list of repo names to ``(profile_name, repo)`` pairs.

    ``[]`` -> ``[(base_name, None)]`` (profile with no ``repo =`` line — aai-cli falls
    back to a ``--repo`` CLI flag). ``[r1, r2, ...]`` ->
    ``[(base_name, r1), (f"{base_name}-2", r2), ...]``.
    """
    if not repos:
        return [(base_name, None)]
    return [(base_name if i == 0 else f"{base_name}-{i + 1}", repo) for i, repo in enumerate(repos)]


def repo_scoped_profile_line(label: str, base: str, scope: str, scope_kind: str, repos: list[str]) -> str:
    """Render the agents_md line for a repo-scoped provider (GitHub/Bitbucket).

    With repos configured, each --profile slug is mapped to the ``scope/repo`` it
    targets (``github-work`` -> ``aai-labs/agent-farm``) so an agent with several repos
    knows which profile is which. With none configured, the profile carries no ``repo``,
    so aai-cli requires ``--repo`` at call time — the line says so, and names the
    ``scope`` (owner/workspace). ``scope`` comes from the configured secret, so this
    reflects whatever org/workspace the operator set up — nothing is hardcoded.
    """
    if repos:
        segments = ", ".join(f"`--profile {name}` → {scope}/{repo}" for name, repo in profile_repo_pairs(base, repos))
        return f"- **{label}**: {segments}"
    return (
        f"- **{label}**: `--profile {base}` ({scope_kind} `{scope}` already set on the "
        "profile; no repo configured — pass `--repo <repo>`)"
    )


class AaiCliIntegration[ContentT: SecretContent]:
    """Per-provider aai-cli behavior, mixed into an ``IntegrationPlugin``."""

    #: Canonical ``--profile`` slug. GitHub/Bitbucket use it as the base for -2, -3, ...
    aai_cli_slug: str
    #: Display label for the agents_md integrations block.
    aai_cli_label: str
    #: One-clause summary of what the integration can do, appended to its agents_md line.
    #: Sourced from the provider's bundled SKILL.md; keep in sync when commands are added.
    #: ``None`` for providers with no bundled skill doc (the calendars).
    aai_cli_capability: str | None = None
    #: ``(secret_name, content_attr)`` pairs for aai-cli's encrypted secret store.
    #: Empty for env-based providers, which inject via ``*_env`` instead.
    aai_cli_secret_entries: tuple[tuple[str, str], ...] = ()

    def aai_cli_profile_block(self, content: ContentT) -> str:
        """Render this provider's ``[profiles.<slug>]`` block for config.toml."""
        raise NotImplementedError

    def aai_cli_gateway_profile_block(self, content: ContentT, *, base_url: str, token_env: str) -> str:
        """Render the ``[profiles.<slug>]`` block for a gateway-routed provider.

        The profile uses aai-cli's existing endpoint override and environment-backed
        authentication fields to point at the credential gateway and send this Agent's
        Gateway Token. It carries no ``*_secret`` reference, because no provider
        credential is materialized into the pod at all.
        """
        raise NotImplementedError

    def aai_cli_context_line(self, content: ContentT) -> str:
        """Line for the "Configured Integrations" block in tools_md.

        Default names the provider and its profile slug. Providers with site or repo
        metadata worth printing override this.
        """
        return f"- **{self.aai_cli_label}** (`{self.aai_cli_slug}`)"

    def aai_cli_policy_line(self, content: ContentT) -> str:
        """Line for the integrations block in agents_md, before the capability clause."""
        return f"- **{self.aai_cli_label}**: `--profile {self.aai_cli_slug}`"


class AaiCliPlugin[ContentT: SecretContent](AaiCliIntegration[ContentT], IntegrationPlugin[ContentT]):
    """An Integration Plugin whose provider is reached by aai-cli.

    Exists so a provider names one base class rather than composing the mixin and the
    plugin at every declaration, and so the adapter has a single type carrying both
    surfaces. The registry still checks ``AaiCliIntegration`` directly, so a plugin that
    composes them by hand remains valid.
    """

    runtime_tool = "aai-cli"
