# Platform administration — change log

Status: Active
Epic: [AF-235](https://aai-labs.atlassian.net/browse/AF-235)
Related context: [Identity and Organizations](../identity-and-organizations.md), [Domain Events](../domain-events.md), [Platform oversight boundary ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md)

## Current state

- Delivered: AF-237 self-service Organization creation, invitation-based Platform user onboarding, per-creator limits, membership-only Organization selection, bounded Platform Privilege administration, explicit Platform/Organization event scopes, and durable Security Audit Record projection.
- Delivered: Platform View now includes allowlisted Organization and user identity detail, Organization membership drill-downs, and dedicated read contracts that exclude tenant configuration.
- Delivered: Platform View reports cross-Organization chat volume and Agent activity as bounded statistics, over preset periods or a custom range, narrowed by Organization, Agent, creator, or chat platform.
- In transition: the remaining Platform Oversight detail/statistics surfaces—per-Organization and per-Agent breakdowns, Tool Call statistics, model usage, costs, suspension, and unified audit exploration—remain deferred under the AF-235 backlog.
- Next: Organization suspension/reactivation, unified audit exploration, and the remaining platform oversight details/statistics are captured in `../../plans/AF-235-remaining-platform-management-tasks.md`.
- Blockers: none for the delivered AF-237 slice.

## Changes

### 2026-08-10 — AF-256 — one implementation PR

- Added: `GET /platform/stats/messages` reports cross-Organization inbound/outbound chat counts and a bucketed series. The window is either a preset period or an explicit `from_date`/`to_date` range; bucket size follows the span (minute under 2 hours, hour under 3 days, day under 90, week beyond) and can be pinned with `granularity`.
- Added: `GET /platform/stats/agents` reports the current status split—every non-deleted Agent, and the RUNNING/STOPPED/ERROR partition of it—alongside the Agents with observable telemetry in the period, plus a series of Agents existing, created, and active per bucket.
- Added: both surfaces narrow by Organization, Agent, Agent creator, and chat platform. There is deliberately no "by sender" filter: sender identity is excluded from these projections, so the contract cannot answer it.
- Added: the Platform page gains an Overview strip of current counts and an Activity section—period and filter controls, tiles, and stacked full-width charts—below the existing administration links.
- Changed: `agent_chat_message` gains `(occurred_at, direction, agent_id)` and `tool_call` gains `(occurred_at, agent_id, organization_id)`. Every pre-existing index on both tables is prefixed by `agent_id`, so none can seek to a platform-wide time range; the trailing columns keep the reads index-only. Built without `CONCURRENTLY`, matching the rest of this repo—see the migration for the write-stall trade-off.
- Kept: counts only. Message content, sender/channel/session identity, and every other tenant fact stay outside these contracts, and both endpoints resolve no Active Organization.
- Note: the aggregates take an optional Organization so a later Organization dashboard reuses them behind its own routes, read models, and AuthorizationScope rather than widening the platform ones.
- Note: messages belonging to soft-deleted Agents stay counted so historical volume survives an Agent's retirement. Deleting an Organization still cascades its messages away, so platform totals do not survive that; retaining them is deliberately out of scope here.
- Note: Agent activity is measured from telemetry—the union of chat messages and Tool Calls, deduplicated per day—not from `agent.started`/`agent.stopped`. Lifecycle events record administrative intent rather than liveness: they are emitted when someone presses start or stop, so an Agent whose pod dies never emits a stop, ERROR transitions emit nothing at all, and no history exists before the outbox shipped. Telemetry answers "did this Agent do work", which is the question the series is for.
- Note: Tool Calls carry disproportionate weight in that union. The runtime plugins gate outbound *messages* on a user-triggered turn, so scheduled and proactive work leaves no message behind and is visible only through its Tool Calls.
- Note: the Overview counts are point-in-time reads of the Agent row and do not move with the selected period, which is why they sit above the period controls rather than among the period-scoped tiles. They do still respect the Organization and platform filters.
- Note: `running` reflects the last recorded status rather than liveness. Activity is always a lower bound on it—an Agent up all day with no traffic is active on none of them.
- Note: series buckets are emitted as UTC instants with an explicit offset. Without one a browser parses them as local time and every chart label shifts by the viewer's timezone.
- Note: a request is rejected when its span and granularity would need more than 5,000 buckets, since `granularity` is caller-supplied and would otherwise let one URL ask for tens of millions.
- Follow-up: per-Agent drill-down, Tool Call statistics, model usage, and cost oversight remain with AF-250.

### 2026-07-31 — AF-237 — one implementation PR

- Delivered: any authenticated user can create an Organization and becomes its immutable Creator and initial Owner; Platform Administrators use the same path and quota.
- Changed: replaced password-setting Platform user creation with invitation-based onboarding that atomically creates the pending User, initial Organization, Owner Membership, and set-password token; platform password reset and account deletion remain removed.
- Changed: kept Organization Name as a non-unique display label; Platform View uses creator identity and Organization ID for disambiguation instead of overloading names as identifiers.
- Changed: removed platform Organization provisioning; added reasoned Platform Privilege grant/revoke, user-session credential enforcement, scoped Domain Events, and deletion-independent Security Audit Records.
- Changed: updated the Organization switcher and Platform users/Organizations pages so the authority and membership boundaries are visible in the UI.
- Added: Platform Organization and user detail pages expose only the allowlisted identity and membership projections supported by the Platform oversight boundary; tenant configuration remains outside these contracts.
- Follow-up: implement the three deferred AF-235 tasks without expanding Platform Administrators into tenant membership or impersonation.
