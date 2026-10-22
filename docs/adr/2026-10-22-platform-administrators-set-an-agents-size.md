# Platform Administrators set one Agent's size

Status: Accepted
Date: 2026-10-22
Origin: Agent Sizes epic, agreed with Kalkidan Betre on 2026-10-21

A Platform Administrator may give one Organization's Agent an Agent Size from Platform View, and while that override stands the Organization cannot change it. This is a narrow exception to [Platform Oversight without Organization access](2026-07-30-platform-oversight-without-organization-access.md): the platform wants Organizations, starting with its own default one, kept from choosing sizes "so people don't go crazy with it", while still giving particular Agents more memory (the first was an Agent at risk of being OOM-killed on large reports). Those Organizations may later be paying customers, which makes CPU and memory a platform-granted allowance rather than an Organization setting.

## Considered alternatives

Letting the Organization choose (the allowed set) would hand the decision to the very Organizations the platform wants to keep locked. Waiting for impersonation, which the oversight ADR reserves for exceptional tenant-scoped action, would leave no way to resize an Agent until impersonation exists, and would give the administrator far more authority than one setting needs.

## Consequences

- The write is the size only: `PUT /platform/agents/{agent_id}/agent-size`. It never starts, stops or reconfigures the Agent, which picks the size up at its next start; restarting stays with the Organization.
- The Platform Agents list adds the Agent's size, whether the platform set it and whether it is pending to the allowlisted Agent identity and lifecycle facts. Configuration stays excluded.
- An override locks the size for the Organization (`409` on its own route) until a Platform Administrator clears it, which returns the Agent to the default.
- Each override and clear is an Organization-scoped `agent.agent_size.changed` Security Audit Record marked `by_platform`, with the administrator's user as actor when they have no Membership there.
- Any further platform write on Organization-owned resources needs its own decision; this one does not generalize.
