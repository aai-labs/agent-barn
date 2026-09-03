"""Contract tests for the Integration Plugin registry.

One parametrized sweep over every shipped plugin, so a new provider cannot be added
half-way. The maps that could not be derived from the registry without an import cycle
(``PROVIDER_DISPLAY_NAMES``, ``PROVIDER_CONTENT_MODELS``, ``PROVIDER_VALIDATORS``) are
pinned here instead: they stay where they are, but they cannot drift silently.
"""

import pytest
from hamcrest import assert_that, contains_inanyorder, equal_to, instance_of, is_, is_not, not_none

from api.domains.agents.aai_cli_skills import AAI_CLI_PROVIDER_SKILLS
from api.domains.agents.models import (
    PROVIDER_CONTENT_MODELS,
    PROVIDER_DISPLAY_NAMES,
    SecretProvider,
)
from api.domains.integrations.plugins.aai_cli_support import AaiCliIntegration, AaiCliPlugin
from api.domains.integrations.plugins.base import EgressMode, IntegrationPlugin, OutboundRequest
from api.domains.integrations.plugins.providers import AAI_CLI, GOG, NO_TOOL
from api.domains.integrations.plugins.registry import (
    INTEGRATION_PLUGINS,
    IntegrationPluginRegistry,
    effective_egress_mode,
)
from api.infrastructure.integration_validators import PROVIDER_VALIDATORS

ALL_PLUGINS = INTEGRATION_PLUGINS.all()
AAI_CLI_PLUGINS: tuple[AaiCliPlugin, ...] = tuple(
    p for p in INTEGRATION_PLUGINS.for_tool(AAI_CLI) if isinstance(p, AaiCliPlugin)
)


def _ids(plugins):
    return [p.key for p in plugins]


# --- registry shape ---


def test_every_secret_provider_has_a_plugin():
    assert_that(_ids(ALL_PLUGINS), contains_inanyorder(*[p.value for p in SecretProvider]))


def test_plugins_are_returned_in_fixed_provider_order():
    # Config.toml, setup.sh, and the agents_md blocks are order-sensitive; the registry
    # is what makes that order a property of the catalogue rather than of each builder.
    assert_that([p.provider for p in ALL_PLUGINS], is_(equal_to(list(SecretProvider))))


def test_for_tool_partitions_the_catalogue():
    partitioned = _ids(INTEGRATION_PLUGINS.for_tool(AAI_CLI)) + _ids(INTEGRATION_PLUGINS.for_tool(GOG))
    partitioned += _ids(INTEGRATION_PLUGINS.for_tool(NO_TOOL))
    assert_that(sorted(partitioned), is_(equal_to(sorted(_ids(ALL_PLUGINS)))))


# --- per-plugin contract ---


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_plugin_key_matches_its_provider(plugin: IntegrationPlugin):
    assert_that(plugin.key, is_(equal_to(plugin.provider.value)))


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_plugin_display_name_matches_the_stamped_label(plugin: IntegrationPlugin):
    assert_that(plugin.display_name, is_(equal_to(PROVIDER_DISPLAY_NAMES[plugin.provider])))


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_plugin_credentials_model_matches_the_provider_content_model(plugin: IntegrationPlugin):
    assert_that(plugin.credentials_model, is_(equal_to(PROVIDER_CONTENT_MODELS[plugin.provider])))


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_plugin_declares_a_live_validator_exactly_when_one_is_registered(plugin: IntegrationPlugin):
    # Providers without a live validator stay schema-validated only; that is a real
    # contract, so the two sources must agree rather than one quietly gaining a provider.
    declares = type(plugin).validate_external is not IntegrationPlugin.validate_external
    assert_that(declares, is_(plugin.provider in PROVIDER_VALIDATORS))


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_plugin_bundled_skill_slugs_exist_in_the_seeded_bundle(plugin: IntegrationPlugin):
    seeded = {skill["slug"] for skill in AAI_CLI_PROVIDER_SKILLS}
    for slug in plugin.bundled_skill_slugs:
        assert_that(slug in seeded, is_(True), f"{plugin.key} names unseeded skill {slug!r}")


@pytest.mark.parametrize("plugin", ALL_PLUGINS, ids=_ids(ALL_PLUGINS))
def test_a_plugin_declaring_gateway_egress_is_still_direct_until_enabled(plugin: IntegrationPlugin):
    # egress_mode is a capability, not a switch. Nothing changes where a credential goes
    # until an operator lists the provider in credential_gateway_providers, so the
    # default configuration must leave every provider DIRECT.
    assert_that(effective_egress_mode(plugin, frozenset()), is_(equal_to(EgressMode.DIRECT)))


def test_github_is_the_only_provider_that_supports_gateway_egress_so_far():
    # Guards the rollout order: a provider gains gateway support in its own slice, with
    # the forwarding tests that go with it.
    supported = [p.key for p in ALL_PLUGINS if p.egress_mode is not EgressMode.DIRECT]
    assert_that(supported, is_(equal_to(["github"])))


def test_enabling_a_provider_that_cannot_proxy_leaves_it_direct():
    # A typo or a stale config entry must not route a provider whose plugin has no
    # upstream behavior — that would 500 on the hot path instead of being a no-op.
    jira = INTEGRATION_PLUGINS.require(SecretProvider.JIRA)
    assert_that(effective_egress_mode(jira, frozenset({"jira"})), is_(equal_to(EgressMode.DIRECT)))


@pytest.mark.parametrize("plugin", AAI_CLI_PLUGINS, ids=_ids(AAI_CLI_PLUGINS))
def test_aai_cli_plugins_implement_the_aai_cli_seam(plugin: AaiCliPlugin):
    assert_that(plugin, is_(instance_of(AaiCliIntegration)))
    assert_that(plugin.aai_cli_slug, is_(not_none()))
    assert_that(plugin.aai_cli_label, is_(not_none()))


def test_aai_cli_profile_slugs_are_unique():
    slugs = [p.aai_cli_slug for p in AAI_CLI_PLUGINS]
    assert_that(sorted(slugs), is_(equal_to(sorted(set(slugs)))))


def test_non_aai_cli_providers_do_not_carry_a_profile():
    # gog takes no --profile and Firecrawl reaches no CLI at all; a profile slug on
    # either would put them in the aai-cli agents_md block, which tells the agent that
    # aai-cli is the only way to reach them.
    for plugin in INTEGRATION_PLUGINS.for_tool(GOG) + INTEGRATION_PLUGINS.for_tool(NO_TOOL):
        assert_that(plugin, is_not(instance_of(AaiCliIntegration)))


# --- egress seams are unimplemented until a provider's slice flips it ---


_DIRECT_ONLY = [p for p in ALL_PLUGINS if p.egress_mode is EgressMode.DIRECT]


@pytest.mark.parametrize("plugin", _DIRECT_ONLY, ids=_ids(_DIRECT_ONLY))
def test_a_provider_without_gateway_support_refuses_the_seams(plugin: IntegrationPlugin):
    content = object()
    with pytest.raises(NotImplementedError):
        plugin.upstream_base_url(content)
    with pytest.raises(NotImplementedError):
        plugin.apply_upstream_auth(content, OutboundRequest("GET", "/"))


# --- registry validation ---


def _plugin(**attrs) -> IntegrationPlugin:
    base = {
        "key": "github",
        "provider": SecretProvider.GITHUB,
        "display_name": "GitHub credential",
        "credentials_model": PROVIDER_CONTENT_MODELS[SecretProvider.GITHUB],
        "runtime_tool": NO_TOOL,
    }
    return type("_Stub", (IntegrationPlugin,), {**base, **attrs})()


def _registry_error(**attrs) -> str:
    with pytest.raises(ValueError) as exc:
        IntegrationPluginRegistry([_plugin(**attrs)])
    return str(exc.value)


def test_registry_rejects_a_non_canonical_key():
    assert_that("canonical lowercase" in _registry_error(key="GitHub"), is_(True))


def test_registry_rejects_a_key_that_disagrees_with_its_provider():
    assert_that("does not match provider" in _registry_error(key="jira"), is_(True))


def test_registry_rejects_an_unknown_runtime_tool():
    assert_that("unknown runtime tool" in _registry_error(runtime_tool="some_service_cli"), is_(True))


def test_registry_rejects_an_aai_cli_plugin_that_skips_the_aai_cli_seam():
    assert_that("does not implement AaiCliIntegration" in _registry_error(runtime_tool=AAI_CLI), is_(True))


def test_registry_rejects_a_gateway_proxy_plugin_with_no_upstream_behavior():
    message = _registry_error(egress_mode=EgressMode.GATEWAY_PROXY)
    assert_that("never overrides upstream_base_url" in message, is_(True))


def test_registry_rejects_a_token_broker_plugin_with_no_minting_behavior():
    message = _registry_error(egress_mode=EgressMode.TOKEN_BROKER)
    assert_that("never overrides mint_upstream_token" in message, is_(True))


def test_registry_rejects_a_catalogue_missing_a_provider():
    # A provider with no plugin would silently lose its credential handling at start.
    with pytest.raises(ValueError) as exc:
        IntegrationPluginRegistry([_plugin()])
    assert_that("No Integration Plugin registered" in str(exc.value), is_(True))


def test_registry_rejects_duplicate_providers():
    with pytest.raises(ValueError) as exc:
        IntegrationPluginRegistry([_plugin(), _plugin()])
    assert_that("Duplicate Integration Plugin provider" in str(exc.value), is_(True))


def test_registry_rejects_a_non_positive_schema_version():
    assert_that("schema version must be positive" in _registry_error(schema_version=0), is_(True))


def test_require_rejects_an_unregistered_provider():
    registry = IntegrationPluginRegistry(INTEGRATION_PLUGINS.all())
    assert_that(registry.require(SecretProvider.GITHUB).key, is_(equal_to("github")))
    assert_that(INTEGRATION_PLUGINS.require(SecretProvider.FIRECRAWL).runtime_tool, is_(equal_to(NO_TOOL)))


def test_google_workspace_is_not_shared_credential_eligible():
    # Its consent is per-agent, so an org-scoped Shared Credential would attach the
    # wrong person's Google account.
    assert_that(INTEGRATION_PLUGINS.require(SecretProvider.GOOGLE_WORKSPACE).shared_credential_eligible, is_(False))
