"""Pure runtime adapters for explicitly selected credential routes.

Startup resolves desired policy before invoking these adapters. They neither read
policy from the database nor issue gateway tokens.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import urlsplit

from api.domains.agents.aai_cli_artifacts import (
    build_env,
    build_integrations_policy_md,
    build_setup_sh,
)
from api.domains.agents.gog_artifacts import (
    build_gog_env,
    build_gog_policy_md,
    build_gog_shim_install_sh,
    build_gog_shim_sh,
)
from api.domains.agents.models import (
    FirecrawlContent,
    GoogleWorkspaceContent,
    SecretContent,
    SecretProvider,
    SharePointContent,
)
from api.domains.credential_gateway.models import gateway_token_env_var
from api.domains.integrations.capabilities import ISOLATION_CAPABILITIES
from api.domains.integrations.gog_direct import build_direct_gog_env, build_direct_gog_setup_sh
from api.domains.integrations.plugins.aai_cli_support import AaiCliIntegration, secrets_dir
from api.domains.integrations.plugins.base import EgressMode, RuntimeArtifacts
from api.domains.integrations.plugins.providers import AAI_CLI, GOG, NO_TOOL, SharePointPlugin
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS


def select_egress_mode(provider: SecretProvider, *, isolated: bool) -> EgressMode:
    capabilities = ISOLATION_CAPABILITIES[provider]
    if isolated:
        if not capabilities.supports_isolated:
            raise ValueError(f"{provider.value} does not support isolation")
        return INTEGRATION_PLUGINS.require(provider).egress_mode
    if not capabilities.supports_direct:
        raise ValueError(f"{provider.value} does not support direct credentials")
    return EgressMode.DIRECT


@dataclass(frozen=True)
class RuntimeBinding:
    provider: SecretProvider
    content: SecretContent = field(repr=False)
    mode: EgressMode


@dataclass(frozen=True)
class RuntimeContext:
    home_dir: str
    gog_home_dir: str
    gateway_base_url: str = ""
    gateway_tokens: Mapping[SecretProvider, str] = field(default_factory=dict, repr=False)
    store_dir: str | None = None
    sharepoint_token_url: str | None = None


class RuntimeToolAdapter(Protocol):
    def materialize(self, bindings: list[RuntimeBinding], context: RuntimeContext) -> RuntimeArtifacts: ...


class AaiCliAdapter:
    def materialize(self, bindings: list[RuntimeBinding], context: RuntimeContext) -> RuntimeArtifacts:
        store_dir = context.store_dir or secrets_dir(context.home_dir)
        # Match the existing file layout; SharePoint's store must remain on its PVC.
        blocks = [
            (
                f"secrets_file = {json.dumps(store_dir + '/aai-secrets.enc.json')}\n"
                f"key_file = {json.dumps(store_dir + '/key')}\n"
            )
        ]
        direct: dict[SecretProvider, SecretContent] = {}
        decrypted: dict[SecretProvider, SecretContent] = {}
        selected_sites = False
        for binding in bindings:
            plugin = INTEGRATION_PLUGINS.require(binding.provider)
            if not isinstance(plugin, AaiCliIntegration):
                raise TypeError(f"{plugin.key} has no aai-cli materializer")
            cli_plugin = cast(AaiCliIntegration[SecretContent], plugin)
            decrypted[binding.provider] = binding.content
            if binding.mode == EgressMode.DIRECT:
                # Missing scoped Atlassian metadata must fail, not silently skip a profile.
                if plugin.egress_mode == EgressMode.GATEWAY_PROXY:
                    plugin.upstream_base_url(binding.content)
                if isinstance(binding.content, SharePointContent) and binding.content.mode == "selected_sites":
                    assert isinstance(plugin, SharePointPlugin)
                    blocks.append(plugin.aai_cli_selected_sites_profile_block(context.sharepoint_token_url))
                    selected_sites = True
                else:
                    blocks.append(cli_plugin.aai_cli_profile_block(binding.content))
                    direct[binding.provider] = binding.content
            else:
                blocks.append(
                    cli_plugin.aai_cli_gateway_profile_block(
                        binding.content,
                        base_url=(
                            f"{context.gateway_base_url.rstrip('/')}/token"
                            if binding.mode == EgressMode.TOKEN_BROKER
                            else f"{context.gateway_base_url.rstrip('/')}/p/{plugin.key}"
                        ),
                        token_env=gateway_token_env_var(binding.provider),
                    )
                )
        files = {
            "aai-cli-setup.sh": build_setup_sh(
                list(direct),
                context.home_dir,
                store_dir=context.store_dir,
                install_config=bool(bindings),
                store_platform_key=selected_sites,
                isolated_providers=[b.provider for b in bindings if b.mode != EgressMode.DIRECT],
            )
        }
        if bindings:
            files["aai-cli-config.toml"] = "\n".join(blocks)
        return RuntimeArtifacts(files=files, env=build_env(direct), policy_md=build_integrations_policy_md(decrypted))


class GogAdapter:
    def materialize(self, bindings: list[RuntimeBinding], context: RuntimeContext) -> RuntimeArtifacts:
        if len(bindings) != 1:
            raise ValueError("gog requires one Google Workspace binding")
        binding = bindings[0]
        content = binding.content
        if not isinstance(content, GoogleWorkspaceContent):
            raise TypeError("gog requires Google Workspace credentials")
        if binding.mode == EgressMode.DIRECT:
            return RuntimeArtifacts(
                files={"gog-setup.sh": build_direct_gog_setup_sh(context.gog_home_dir)},
                env=build_direct_gog_env(content, context.gog_home_dir),
                policy_md=build_gog_policy_md(content),
            )
        return RuntimeArtifacts(
            files={
                "gog-setup.sh": build_gog_shim_install_sh(context.gog_home_dir),
                "gog-shim.sh": build_gog_shim_sh(),
            },
            env=build_gog_env(content, context.gog_home_dir, gateway_base_url=context.gateway_base_url),
            policy_md=build_gog_policy_md(content),
        )


class NoToolAdapter:
    """Firecrawl environment for a stored credential or the operator default binding."""

    def materialize(self, bindings: list[RuntimeBinding], context: RuntimeContext) -> RuntimeArtifacts:
        if len(bindings) != 1:
            raise ValueError("The env-only adapter requires one Firecrawl binding")
        binding = bindings[0]
        content = binding.content
        if not isinstance(content, FirecrawlContent):
            raise TypeError("The env-only adapter requires Firecrawl credentials")
        if content.base_url:
            target = urlsplit(content.base_url)
            if (
                target.scheme not in {"http", "https"}
                or not target.hostname
                or target.username
                or target.password
                or target.query
                or target.fragment
            ):
                raise ValueError("Invalid Firecrawl endpoint")
        plugin = INTEGRATION_PLUGINS.require(binding.provider)
        if binding.mode == EgressMode.DIRECT:
            api_key = content.api_key
            base_url = content.base_url or plugin.upstream_base_url(content)
        else:
            api_key = context.gateway_tokens[binding.provider]
            base_url = f"{context.gateway_base_url.rstrip('/')}/p/{plugin.key}"
        return RuntimeArtifacts(env={"FIRECRAWL_API_KEY": api_key, "FIRECRAWL_API_URL": base_url})


RUNTIME_TOOL_ADAPTERS: Mapping[str, RuntimeToolAdapter] = {
    AAI_CLI: AaiCliAdapter(),
    GOG: GogAdapter(),
    NO_TOOL: NoToolAdapter(),
}


def materialize_integrations(bindings: Iterable[RuntimeBinding], context: RuntimeContext) -> RuntimeArtifacts:
    """Validate the entire selection before producing any runtime credential artifacts."""
    by_provider: dict[SecretProvider, RuntimeBinding] = {}
    grouped: dict[str, list[RuntimeBinding]] = {}
    for binding in bindings:
        plugin = INTEGRATION_PLUGINS.require(binding.provider)
        if binding.provider in by_provider:
            raise ValueError(f"Duplicate binding for {plugin.key}")
        if not isinstance(binding.content, plugin.credentials_model):
            raise TypeError(f"Credential type disagrees with {plugin.key}")
        if binding.mode != select_egress_mode(binding.provider, isolated=binding.mode != EgressMode.DIRECT):
            raise ValueError(f"Unsupported credential route for {plugin.key}")
        if binding.mode != EgressMode.DIRECT and (
            not context.gateway_base_url or not context.gateway_tokens.get(binding.provider)
        ):
            raise ValueError(f"Missing gateway authorization for {plugin.key}")
        if plugin.runtime_tool not in RUNTIME_TOOL_ADAPTERS:
            raise ValueError(f"No runtime adapter for {plugin.runtime_tool}")
        by_provider[binding.provider] = binding
    for provider in SecretProvider:
        binding = by_provider.get(provider)
        if binding is not None:
            tool = INTEGRATION_PLUGINS.require(provider).runtime_tool
            grouped.setdefault(tool, []).append(binding)

    files: dict[str, str] = {}
    env: dict[str, str] = {}
    policies: list[str] = []
    # Always retain aai-cli setup, including removal cleanup for SharePoint's persistent store.
    grouped.setdefault(AAI_CLI, [])
    for tool, selected in grouped.items():
        artifacts = RUNTIME_TOOL_ADAPTERS[tool].materialize(selected, context)
        if files.keys() & artifacts.files.keys() or env.keys() & artifacts.env.keys():
            raise ValueError("Runtime adapters produced conflicting artifacts")
        files.update(artifacts.files)
        env.update(artifacts.env)
        policies.append(artifacts.policy_md)
    for binding in by_provider.values():
        if binding.mode != EgressMode.DIRECT:
            env[gateway_token_env_var(binding.provider)] = context.gateway_tokens[binding.provider]
    if any(binding.mode != EgressMode.DIRECT for binding in by_provider.values()):
        env["AF_GATEWAY_URL"] = context.gateway_base_url
    return RuntimeArtifacts(files=files, env=env, policy_md="".join(policies))
