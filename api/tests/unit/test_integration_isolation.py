from dataclasses import replace
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, is_, none

from api.domains.agents.models import AgentSecret, SecretProvider
from api.domains.integrations.capabilities import ISOLATION_CAPABILITIES, validate_isolation_capabilities
from api.domains.integrations.isolation import default_isolation, isolation_read, legacy_isolation, resolve_binding
from api.domains.integrations.models import AgentIntegrationIsolation
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS


@pytest.mark.parametrize("provider", list(SecretProvider))
def test_foundation_default_preserves_current_route(provider):
    read = isolation_read(provider, None)
    assert_that(read.desired, is_(provider != SecretProvider.SHAREPOINT))
    assert_that(read.switch_available, is_(True))
    assert_that(read.applied, is_(none()))
    assert_that(default_isolation(provider), is_(False))


def test_legacy_default_is_independent_of_later_plugin_changes(monkeypatch):
    plugin = INTEGRATION_PLUGINS.require(SecretProvider.GITHUB)
    monkeypatch.setattr(plugin, "egress_mode", EgressMode.DIRECT)
    assert_that(legacy_isolation(SecretProvider.GITHUB), is_(True))


def test_only_broker_descriptions_mention_expiring_access():
    for provider in SecretProvider:
        description = isolation_read(provider, None).isolated_description
        assert_that(
            "expiring" in description, is_(provider in {SecretProvider.GOOGLE_WORKSPACE, SecretProvider.SHAREPOINT})
        )
    assert_that(isolation_read(SecretProvider.GOOGLE_WORKSPACE, None).supported_modes, equal_to(["direct", "isolated"]))
    assert_that(isolation_read(SecretProvider.SHAREPOINT, None).supported_modes, equal_to(["direct", "isolated"]))


@pytest.mark.parametrize("shared", [False, True])
def test_binding_derives_source_and_preserves_stored_intent(shared):
    secret = AgentSecret(
        agent_id=uuid7(),
        provider=SecretProvider.GITHUB,
        secret_name="GitHub",
        content=None if shared else "encrypted",
        shared_credential_id=uuid7() if shared else None,
    )
    policy = AgentIntegrationIsolation(agent_id=secret.agent_id, provider=SecretProvider.GITHUB, isolated=False)
    binding = resolve_binding(SecretProvider.GITHUB, secret, policy)
    assert binding is not None
    assert_that(binding.source, equal_to("shared_credential" if shared else "agent_secret"))
    assert_that(binding.isolation.desired, is_(False))


def test_default_firecrawl_remains_direct_without_creating_a_policy():
    binding = resolve_binding(SecretProvider.FIRECRAWL, None, None, firecrawl_default_configured=True)
    assert binding is not None
    assert_that(binding.source, equal_to("platform_default"))
    assert_that(binding.isolation.desired, is_(False))
    assert_that(resolve_binding(SecretProvider.FIRECRAWL, None, None), is_(none()))
    assert_that(resolve_binding(SecretProvider.GITHUB, None, None, firecrawl_default_configured=True), is_(none()))


def test_binding_refuses_another_agents_policy():
    secret = AgentSecret(agent_id=uuid7(), provider=SecretProvider.GITHUB, secret_name="GitHub", content="encrypted")
    policy = AgentIntegrationIsolation(agent_id=uuid7(), provider=SecretProvider.GITHUB, isolated=True)
    with pytest.raises(ValueError, match="binding disagree"):
        resolve_binding(SecretProvider.GITHUB, secret, policy)


def test_capability_validation_refuses_missing_provider_copy():
    plugin = INTEGRATION_PLUGINS.require(SecretProvider.GITHUB)
    capabilities = replace(ISOLATION_CAPABILITIES[SecretProvider.GITHUB], isolated_description="")
    with pytest.raises(ValueError, match="describe both"):
        validate_isolation_capabilities(plugin, capabilities)
