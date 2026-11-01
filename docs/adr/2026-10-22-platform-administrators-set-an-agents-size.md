# Platform Administrators set one Agent's size

Status: Accepted
Date: 2026-10-22
Amended: 2026-10-23, Platform Administrators restart any Agent, per the epic's acceptance criteria

A Platform Administrator may give one Organization's Agent an Agent Size from Platform View, and while that override stands the Organization cannot change it. This is a narrow exception to [Platform Oversight without Organization access](2026-07-30-platform-oversight-without-organization-access.md): the platform wants Organizations, starting with its own default one, kept from choosing sizes freely, while still giving particular Agents more memory (the first was an Agent at risk of being OOM-killed on large reports). Those Organizations may later be paying customers, which makes CPU and memory a platform-granted allowance rather than an Organization setting.

## Considered alternatives

Letting the Organization choose (the allowed set) would hand the decision to the very Organizations the platform wants to keep locked. Waiting for impersonation, which the oversight ADR reserves for exceptional tenant-scoped action, would leave no way to resize an Agent until impersonation exists, and would give the administrator far more authority than one setting needs.

## Consequences

- The size write, `PUT /platform/agents/{agent_id}/agent-size`, never starts, stops or reconfigures the Agent, which picks the size up at its next start.
- A second write applies it: `POST /platform/agents/{agent_id}/restart` restarts any Agent, or starts one that is not running. The epic's acceptance criteria say that "by default only platform admins can set this and restart the agent (any)", so the size can take effect without waiting on the Organization. It goes through the Agent's normal lifecycle (its lock, the managed-update and restore-point guards, the same provisioning), changes nothing else, and is recorded by the Agent's ordinary `agent.stopped` and `agent.started` Events with the administrator as actor. The Organization keeps its own start, stop and restart.
- The Platform Agents list adds the Agent's size, whether the platform set it and whether it is pending to the allowlisted Agent identity and lifecycle facts. Configuration stays excluded.
- An override locks the size for the Organization (`409` on its own route) until a Platform Administrator clears it, which returns the Agent to the default.
- Each override and clear is an Organization-scoped `agent.agent_size.changed` Security Audit Record marked `by_platform`, with the administrator's user as actor when they have no Membership there.
- Any further platform write on Organization-owned resources needs its own decision; these two do not generalize.
