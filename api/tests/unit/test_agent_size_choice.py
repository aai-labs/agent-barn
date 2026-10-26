"""Choosing an Agent Size: which size an Agent resolves to, when a restart would change it, and
who may choose. The HTTP surface is covered by tests/integration/test_organization_agent_sizes.py."""

from unittest.mock import MagicMock
from uuid import UUID, uuid7

import pytest
from hamcrest import assert_that, contains_exactly, equal_to, has_item, is_not

from api.domains.agent_sizes.lookup import AgentSizeCatalog, AgentSizeLookupService, MissingDefaultAgentSize
from api.domains.agent_sizes.models import GIB, MIB, AgentSize, size_is_pending, size_resources
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.api_keys.models import ApiKeyAccessMode
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import (
    AGENT_OWNER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    SYSTEM_AGENT_ACCESS_ROLE_GRANTS,
    OrganizationRole,
    PermissionKey,
    organization_role_allows,
)
from api.domains.rbac.policy import PermissionPolicy
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser


def _size(name: str, *, is_default: bool = False, enabled: bool = True, sort_order: int = 0, scale: int = 1):
    return AgentSize(
        id=uuid7(),
        name=name,
        cpu_request_millicores=50 * scale,
        cpu_limit_millicores=500 * scale,
        memory_request_bytes=320 * MIB * scale,
        memory_limit_bytes=1 * GIB * scale,
        enabled=enabled,
        is_default=is_default,
        sort_order=sort_order,
    )


STANDARD = _size("Standard", is_default=True)
LARGE = _size("Large", scale=2, sort_order=1)
HUGE = _size("Huge", scale=4, sort_order=2)
RETIRED = _size("Retired", scale=3, sort_order=3, enabled=False)


# --- resolution ----------------------------------------------------------------


def test_an_agent_resolves_to_its_chosen_size():
    catalog = AgentSizeCatalog(sizes={size.id: size for size in (STANDARD, LARGE)}, default=STANDARD)

    assert_that(catalog.resolve(LARGE.id), equal_to(LARGE))


def test_an_agent_that_never_chose_follows_the_default():
    catalog = AgentSizeCatalog(sizes={size.id: size for size in (STANDARD, LARGE)}, default=STANDARD)

    assert_that(catalog.resolve(None), equal_to(STANDARD))


def test_a_disabled_size_still_applies_to_the_agents_on_it():
    repository = MagicMock()
    repository.get.return_value = RETIRED

    assert_that(AgentSizeLookupService(repository).resolve(RETIRED.id), equal_to(RETIRED))


def test_resolution_without_a_default_says_the_catalog_is_broken():
    repository = MagicMock()
    repository.get_default.return_value = None

    with pytest.raises(MissingDefaultAgentSize):
        AgentSizeLookupService(repository).resolve(None)


def test_an_organization_chooses_from_the_default_then_its_enabled_allowed_sizes():
    repository = MagicMock()
    repository.list_all.return_value = [STANDARD, LARGE, HUGE, RETIRED]
    # Allowed: Large, Retired (disabled since), and the default (never offered twice).
    repository.allowed_size_ids.return_value = {LARGE.id, RETIRED.id, STANDARD.id}

    choosable = AgentSizeLookupService(repository).choosable(uuid7())

    assert_that([size.name for size in choosable], contains_exactly("Standard", "Large"))


def test_an_organization_allowed_nothing_chooses_only_the_default():
    repository = MagicMock()
    repository.list_all.return_value = [STANDARD, LARGE]
    repository.allowed_size_ids.return_value = set()

    assert_that(AgentSizeLookupService(repository).choosable(uuid7()), contains_exactly(STANDARD))


# --- pending size --------------------------------------------------------------


def test_a_stopped_agent_has_nothing_pending():
    assert_that(size_is_pending(None, LARGE), equal_to(False))


def test_a_running_agent_on_its_size_has_nothing_pending():
    assert_that(size_is_pending(size_resources(STANDARD), STANDARD), equal_to(False))


def test_choosing_another_size_while_running_is_pending():
    assert_that(size_is_pending(size_resources(STANDARD), LARGE), equal_to(True))


def test_editing_the_size_an_agent_runs_on_is_pending():
    edited = STANDARD.model_copy(update={"memory_limit_bytes": 2 * GIB})

    assert_that(size_is_pending(size_resources(STANDARD), edited), equal_to(True))


# --- who may choose ------------------------------------------------------------


def test_the_permission_matches_the_migration_that_catalogued_it():
    """Startup refuses a catalogue that differs from the database by a single row."""
    assert_that(
        PERMISSION_ID_BY_KEY[PermissionKey.AGENT_SIZE_MANAGE],
        equal_to(UUID("bdca6a6b-54cd-5741-98ef-6cdc10cfea69")),
    )


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(OrganizationRole.OWNER, True), (OrganizationRole.ADMIN, True), (OrganizationRole.MEMBER, False)],
)
def test_only_owners_and_admins_choose_sizes(role, allowed):
    assert_that(organization_role_allows(role, PermissionKey.AGENT_SIZE_MANAGE), equal_to(allowed))


def test_no_agent_access_role_carries_the_size_permission():
    """An Agent's own Owner or Editor cannot spend the Organization's capacity."""
    holders = [
        role for role, grants in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.items() if PermissionKey.AGENT_SIZE_MANAGE in grants
    ]
    assert_that(holders, equal_to([]))


def _context(role: OrganizationRole, access_mode: ApiKeyAccessMode | None = None) -> CurrentUserContext:
    organization_id = uuid7()
    user = User(id=uuid7(), email="member@example.com", full_name="Member", hashed_password="x")
    membership = OrganizationUser(id=uuid7(), user_id=user.id, organization_id=organization_id, role=role)
    return CurrentUserContext(
        user=user,
        organization_ids=[organization_id],
        user_organization_map={organization_id: membership},
        current_user_organization=membership,
        api_key_access_mode=access_mode,
    )


def _allowed_actions(context: CurrentUserContext, grants: set[PermissionKey] | None = None) -> list[PermissionKey]:
    agent = Agent(id=uuid7(), organization_id=context.require_current_user_organization().organization_id, name="A")
    repository = MagicMock()
    repository.find_agent_permissions.return_value = {agent.id: grants or set()}
    return AgentAuthorization(PermissionPolicy(), repository).allowed_actions(context, [agent])[agent.id]


@pytest.mark.parametrize("role", [OrganizationRole.OWNER, OrganizationRole.ADMIN])
def test_owners_and_admins_are_offered_the_size_action(role):
    assert_that(_allowed_actions(_context(role)), has_item(PermissionKey.AGENT_SIZE_MANAGE))


def test_an_agent_owner_who_is_a_member_is_not_offered_the_size_action():
    actions = _allowed_actions(
        _context(OrganizationRole.MEMBER), set(SYSTEM_AGENT_ACCESS_ROLE_GRANTS[AGENT_OWNER_ROLE_ID])
    )

    assert_that(actions, is_not(has_item(PermissionKey.AGENT_SIZE_MANAGE)))


def test_a_read_only_key_is_not_offered_the_size_action():
    actions = _allowed_actions(_context(OrganizationRole.OWNER, ApiKeyAccessMode.READ_ONLY))

    assert_that(actions, is_not(has_item(PermissionKey.AGENT_SIZE_MANAGE)))
