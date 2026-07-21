from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class PermissionKey(str, Enum):
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_DELETE = "organization.delete"
    ORGANIZATION_OWNERSHIP_TRANSFER = "organization.ownership.transfer"
    MEMBERSHIP_READ = "membership.read"
    MEMBERSHIP_INVITE = "membership.invite"
    MEMBERSHIP_ROLE_UPDATE = "membership.role.update"
    MEMBERSHIP_REMOVE = "membership.remove"
    AGENT_CREATE = "agent.create"
    AGENT_READ = "agent.read"
    AGENT_UPDATE = "agent.update"
    AGENT_DELETE = "agent.delete"
    AGENT_START = "agent.start"
    AGENT_STOP = "agent.stop"
    AGENT_ACCESS_MANAGE = "agent.access.manage"
    AGENT_SECRET_MANAGE = "agent.secret.manage"
    TEMPLATE_READ = "template.read"
    TEMPLATE_MANAGE = "template.manage"
    SKILL_READ = "skill.read"
    SKILL_MANAGE = "skill.manage"
    ACTIVITY_READ = "activity.read"
    COST_READ = "cost.read"
    AUDIT_READ = "audit.read"


@dataclass(frozen=True)
class RoleSeed:
    id: UUID
    name: str


@dataclass(frozen=True)
class PermissionSeed:
    id: UUID
    key: PermissionKey


OWNER_ROLE_ID = UUID("5dd0b6b3-2a19-5d6d-9c91-50f9503563a6")
ADMIN_ROLE_ID = UUID("1222b10c-3f24-54ca-bbeb-fce956134f70")
MEMBER_ROLE_ID = UUID("d369b23a-01dd-5aeb-bd53-c463b3c4cd1a")

AGENT_OWNER_ROLE_ID = UUID("8f2a47ff-7caf-5ded-9027-4a16b85620b3")
AGENT_EDITOR_ROLE_ID = UUID("30e5e846-5e24-548f-a068-2505f774ce35")
AGENT_VIEWER_ROLE_ID = UUID("c7da77aa-bf9c-5626-8bad-5e0ca5159b5d")

SYSTEM_ROLES: tuple[RoleSeed, ...] = (
    RoleSeed(id=OWNER_ROLE_ID, name="OWNER"),
    RoleSeed(id=ADMIN_ROLE_ID, name="ADMIN"),
    RoleSeed(id=MEMBER_ROLE_ID, name="MEMBER"),
)
SYSTEM_ROLE_ID_BY_NAME = {role.name: role.id for role in SYSTEM_ROLES}
SYSTEM_ROLE_NAME_BY_ID = {role.id: role.name for role in SYSTEM_ROLES}

SYSTEM_AGENT_ACCESS_ROLES: tuple[RoleSeed, ...] = (
    RoleSeed(id=AGENT_OWNER_ROLE_ID, name="OWNER"),
    RoleSeed(id=AGENT_EDITOR_ROLE_ID, name="EDITOR"),
    RoleSeed(id=AGENT_VIEWER_ROLE_ID, name="VIEWER"),
)
SYSTEM_AGENT_ACCESS_ROLE_ID_BY_NAME = {
    role.name: role.id for role in SYSTEM_AGENT_ACCESS_ROLES
}
SYSTEM_AGENT_ACCESS_ROLE_NAME_BY_ID = {
    role.id: role.name for role in SYSTEM_AGENT_ACCESS_ROLES
}

PERMISSIONS: tuple[PermissionSeed, ...] = (
    PermissionSeed(
        UUID("9652eb48-fd1c-5880-b578-4549365e17f3"), PermissionKey.ORGANIZATION_READ
    ),
    PermissionSeed(
        UUID("2cae72d2-b48b-5919-9fb3-ab50b8319ea5"), PermissionKey.ORGANIZATION_UPDATE
    ),
    PermissionSeed(
        UUID("aea08f54-5f04-5093-92ce-42a066b0bbce"), PermissionKey.ORGANIZATION_DELETE
    ),
    PermissionSeed(
        UUID("1589db95-014e-5b17-8bc9-90b6187a3900"),
        PermissionKey.ORGANIZATION_OWNERSHIP_TRANSFER,
    ),
    PermissionSeed(
        UUID("1c7bffa3-5b36-5abc-be31-4f7aacd7252e"), PermissionKey.MEMBERSHIP_READ
    ),
    PermissionSeed(
        UUID("40cade27-b0b2-5657-91ba-95ac1392ff51"), PermissionKey.MEMBERSHIP_INVITE
    ),
    PermissionSeed(
        UUID("6f05fb49-ba9b-5082-be5b-c1e461873d5c"),
        PermissionKey.MEMBERSHIP_ROLE_UPDATE,
    ),
    PermissionSeed(
        UUID("20fd8db9-78c5-51bd-9377-a37f75c55649"), PermissionKey.MEMBERSHIP_REMOVE
    ),
    PermissionSeed(
        UUID("601c6540-6a18-5244-b610-10a4763cf4aa"), PermissionKey.AGENT_CREATE
    ),
    PermissionSeed(
        UUID("76bba6c5-b1bc-5fc2-af28-1eb57bb81fec"), PermissionKey.AGENT_READ
    ),
    PermissionSeed(
        UUID("86500651-f05b-5c39-bb56-dc7dcd154cd6"), PermissionKey.AGENT_UPDATE
    ),
    PermissionSeed(
        UUID("86b3798f-3409-5f7d-bbc2-2d260cfd96d1"), PermissionKey.AGENT_DELETE
    ),
    PermissionSeed(
        UUID("61db56c3-339c-51d7-ab33-b6afbaa9fc8a"), PermissionKey.AGENT_START
    ),
    PermissionSeed(
        UUID("b7355e30-138f-5e19-a8fd-939fe8e34c91"), PermissionKey.AGENT_STOP
    ),
    PermissionSeed(
        UUID("8c5ae860-1a12-52e0-8902-de39b94e8145"), PermissionKey.AGENT_ACCESS_MANAGE
    ),
    PermissionSeed(
        UUID("4412d59f-4e8c-5e7e-81a9-b257f99f9dbf"), PermissionKey.AGENT_SECRET_MANAGE
    ),
    PermissionSeed(
        UUID("a07c3af3-17d6-53cf-841a-80d509b94de4"), PermissionKey.TEMPLATE_READ
    ),
    PermissionSeed(
        UUID("7b44d5da-b324-586b-9d32-d9c49c293037"), PermissionKey.TEMPLATE_MANAGE
    ),
    PermissionSeed(
        UUID("36494947-1572-5cdd-8853-79a2bdbf8c4f"), PermissionKey.SKILL_READ
    ),
    PermissionSeed(
        UUID("222ab95b-f67b-5275-8139-3f601574f3e1"), PermissionKey.SKILL_MANAGE
    ),
    PermissionSeed(
        UUID("3f24e385-7c5e-56f0-828c-502985376af9"), PermissionKey.ACTIVITY_READ
    ),
    PermissionSeed(
        UUID("b6557147-248a-5d34-8bb2-7c51944d9ee7"), PermissionKey.COST_READ
    ),
    PermissionSeed(
        UUID("9143455b-b4d6-58d6-9968-2086e9a24ebf"), PermissionKey.AUDIT_READ
    ),
)
PERMISSION_ID_BY_KEY = {permission.key: permission.id for permission in PERMISSIONS}

_AGENT_OPERATION_KEYS = frozenset(
    {
        PermissionKey.AGENT_READ,
        PermissionKey.AGENT_UPDATE,
        PermissionKey.AGENT_DELETE,
        PermissionKey.AGENT_START,
        PermissionKey.AGENT_STOP,
        PermissionKey.AGENT_ACCESS_MANAGE,
        PermissionKey.AGENT_SECRET_MANAGE,
    }
)
_OWNER_ORGANIZATION_KEYS = frozenset(PermissionKey) - _AGENT_OPERATION_KEYS
_ADMIN_ORGANIZATION_KEYS = _OWNER_ORGANIZATION_KEYS - {
    PermissionKey.ORGANIZATION_DELETE,
    PermissionKey.ORGANIZATION_OWNERSHIP_TRANSFER,
}
_MEMBER_ORGANIZATION_KEYS = frozenset(
    {
        PermissionKey.ORGANIZATION_READ,
        PermissionKey.AGENT_CREATE,
        PermissionKey.TEMPLATE_READ,
        PermissionKey.SKILL_READ,
    }
)

SYSTEM_ROLE_GRANTS: dict[UUID, frozenset[PermissionKey]] = {
    OWNER_ROLE_ID: _OWNER_ORGANIZATION_KEYS,
    ADMIN_ROLE_ID: _ADMIN_ORGANIZATION_KEYS,
    MEMBER_ROLE_ID: _MEMBER_ORGANIZATION_KEYS,
}

_VIEWER_KEYS = frozenset(
    {
        PermissionKey.AGENT_READ,
        PermissionKey.ACTIVITY_READ,
        PermissionKey.COST_READ,
    }
)
_EDITOR_KEYS = _VIEWER_KEYS | {
    PermissionKey.AGENT_UPDATE,
    PermissionKey.AGENT_START,
    PermissionKey.AGENT_STOP,
    PermissionKey.AGENT_SECRET_MANAGE,
}
_OWNER_KEYS = _EDITOR_KEYS | {
    PermissionKey.AGENT_DELETE,
    PermissionKey.AGENT_ACCESS_MANAGE,
}
SYSTEM_AGENT_ACCESS_ROLE_GRANTS: dict[UUID, frozenset[PermissionKey]] = {
    AGENT_VIEWER_ROLE_ID: _VIEWER_KEYS,
    AGENT_EDITOR_ROLE_ID: _EDITOR_KEYS,
    AGENT_OWNER_ROLE_ID: _OWNER_KEYS,
}


def system_role_id(role_name: str) -> UUID:
    try:
        return SYSTEM_ROLE_ID_BY_NAME[role_name]
    except KeyError as exc:
        raise ValueError(f"Unknown system role: {role_name}") from exc


def system_role_name(role_id: UUID) -> str:
    try:
        return SYSTEM_ROLE_NAME_BY_ID[role_id]
    except KeyError as exc:
        raise ValueError(f"Role {role_id} is not a seeded system role") from exc


def system_agent_access_role_id(role_name: str) -> UUID:
    try:
        return SYSTEM_AGENT_ACCESS_ROLE_ID_BY_NAME[role_name]
    except KeyError as exc:
        raise ValueError(f"Unknown system Agent Access Role: {role_name}") from exc


def system_agent_access_role_name(role_id: UUID) -> str:
    try:
        return SYSTEM_AGENT_ACCESS_ROLE_NAME_BY_ID[role_id]
    except KeyError as exc:
        raise ValueError(f"Role {role_id} is not a seeded Agent Access Role") from exc
