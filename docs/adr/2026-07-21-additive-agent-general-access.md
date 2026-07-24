# Additive Agent General Access uses an Agent role reference

Status: Accepted
Date: 2026-07-21
Origin: [AF-231](https://aai-labs.atlassian.net/browse/AF-231)

Agent Farm represents Agent General Access as one nullable Agent-level Agent Access Role reference: `agent.general_access_role_id`. `NULL` means Restricted, while a role ID means All current and future accepted Organization Members receive that role's Permissions for the Agent. This preserves Agent General Access as a dynamic, additive authorization source without materializing per-Membership rows or overloading explicit Agent Access.

## Considered alternatives

- Add a nullable `general_access_role_id` foreign key to `agent`. This keeps the setting on the Agent aggregate, makes Restricted the default for new and migrated Agents, lets visibility queries combine explicit Agent Access with Agent General Access before counting and pagination, and uses `ON DELETE RESTRICT` plus a role-scope trigger to protect referenced roles.
- Store Agent General Access in a separate table keyed by `agent_id`. This keeps the Agent table narrower, but every list/detail/effective-permission query needs another join and the absence of a row becomes a second representation of Restricted.
- Use a sentinel `agent_access` row with no Membership. This reuses the direct-grant table superficially, but breaks the invariant that Agent Access relates one Membership to one Agent, complicates uniqueness, and risks leaking the sentinel into explicit assignment-list, grant, change, and revoke behavior.
- Materialize one Agent Access row per accepted Organization Member. This makes read queries look like direct grants, but turns a dynamic audience into stale bulk data, makes future accepted Members require fan-out writes, and makes revocation semantics misleading because removing a direct grant should fall back to Agent General Access rather than remove it.

## Consequences

Agent authorization resolves an additive union: implicit Organization Owner/Admin authority, explicit Agent Access Permissions, and applicable Agent General Access Permissions. Neither explicit Agent Access nor Agent General Access can reduce Permissions from the other source. Removing a direct Member grant leaves Agent General Access intact; removing Agent General Access leaves direct grants intact.

Only accepted Organization Members receive Agent General Access. Pending or removed Memberships do not receive it, even when the Agent has an All Organization Members role set. Organization Owner/Admin and superuser in explicit Organization context continue to use implicit Agent Owner authority.

The database enforces referenced-role existence, deletion protection, and same-Organization custom-role scope for the Agent-level reference. Application validation performs the same role-availability check and additionally rejects roles that do not grant `agent.read`. Custom Agent Access Role CRUD remains owned by AF-216; role Permission edits take effect on the next request, and deletion of a referenced role must surface as a conflict until the reference is reassigned or removed.
