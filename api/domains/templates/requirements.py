"""Pure helpers for interpreting a template's required-skill map.

A required-skill map is `{skill_id: group_key | None}` as persisted by
`AgentTemplateSkill.group_key`: `None` means the skill is a standalone
AND-required skill (the original, pre-OR-group behavior); skills sharing the
same non-None group_key form an "at least one of" requirement group.
"""

from uuid import UUID


def split_requirements(req_map: dict[UUID, str | None]) -> tuple[set[UUID], dict[str, set[UUID]]]:
    """Split a required-skill map into standalone ids and OR-groups keyed by group_key."""
    standalone_ids: set[UUID] = set()
    groups: dict[str, set[UUID]] = {}
    for skill_id, group_key in req_map.items():
        if group_key is None:
            standalone_ids.add(skill_id)
        else:
            groups.setdefault(group_key, set()).add(skill_id)
    return standalone_ids, groups


def effective_required_ids(req_map: dict[UUID, str | None], assigned_ids: set[UUID]) -> set[UUID]:
    """Skills that are un-removable given what's currently assigned: every
    standalone required skill, plus any group member that is the sole
    assigned member of its group (removing it would empty the group)."""
    standalone_ids, groups = split_requirements(req_map)
    required = set(standalone_ids)
    for members in groups.values():
        assigned_members = members & assigned_ids
        if len(assigned_members) == 1:
            required |= assigned_members
    return required
