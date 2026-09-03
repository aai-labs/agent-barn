# Platform administration — change log

Status: Active
Epic: [AF-235](https://aai-labs.atlassian.net/browse/AF-235)
Related context: [Identity and Organizations](../identity-and-organizations.md), [Domain Events](../domain-events.md), [Platform oversight boundary ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md)

## Current state

- Delivered: AF-237 self-service Organization creation, invitation-based Platform user onboarding, per-creator limits, membership-only Organization selection, bounded Platform Privilege administration, explicit Platform/Organization event scopes, and durable Security Audit Record projection.
- Delivered: Platform View now includes allowlisted Organization and user identity detail, Organization membership drill-downs, and dedicated read contracts that exclude tenant configuration.
- Delivered: Platform View reports cross-Organization chat volume and Agent activity as bounded statistics, over preset periods or a custom range, narrowed by Organization, Agent, creator, or chat platform. Every number is defined under Metric definitions below and asserted by the contract suite.
- In transition: the remaining Platform Oversight detail/statistics surfaces—per-Organization and per-Agent breakdowns, Tool Call statistics, model usage, costs, suspension, and unified audit exploration—remain deferred under the AF-235 backlog.
- Next: Organization suspension/reactivation, unified audit exploration, and the remaining platform oversight details/statistics are captured in `../../plans/AF-235-remaining-platform-management-tasks.md`.
- Blockers: none for the delivered AF-237 slice.

## Metric definitions

The authoritative meaning of every number on the Platform View stats panel.
`api/tests/integration/test_platform_stats.py` asserts each row against a single
fixture built through the Communications Gateway, so these are executable rather
than aspirational.

| Number | Counts | Lifecycle rule |
| --- | --- | --- |
| Agents / Running / Stopped / Errored | Non-deleted Agents right now; the three statuses partition the total | Point-in-time |
| Messages / Received / Sent | Message rows in the window, by direction | Historical |
| Active agents | Distinct Agents with a message **or** a Tool Call in the window, deduplicated | Historical |
| Messages series | Per-bucket inbound/outbound, gap-filled with zeros; sums to its tiles | Historical |
| Agents series `existing` / `created` | Inventory reconstructed from `created_at`/`deleted_at` | Historical |
| Agents series `active` | Per-bucket slice of Active agents; the union over buckets equals the tile | Historical |

Two rules resolve every filter question:

- **Point-in-time counts exclude retired Communication Connections; historical
  aggregates include them.** Deleting an Agent retires its Connections, so
  applying the live-only rule to history would erase an Agent's whole past the
  moment it was removed — the same reasoning that already keeps a soft-deleted
  Agent's messages counted.
- **The messaging app is a property of the message's own Connection, not of its
  Agent.** An Agent connected to both Slack and Telegram has each message
  counted under the app it actually arrived on, never all of them under both.
  Tool Calls carry no Connection, so they fall back to the Agent's Connections.

Two definitions changed with the AF-271 communications rewrite and are recorded
here rather than restored:

- **Sent** counts inbound Communication Deliveries that were answered, not
  provider messages emitted. The reply endpoint requires the delivery it
  answers and is keyed on that delivery's id, so a reply split across several
  provider messages is one row and a second reply to the same delivery is none.
- **Proactive Agent messages are not represented.** No gateway path exists for
  an Agent to send without an inbound delivery to reply to, so anything an Agent
  says on its own initiative leaves no message row and appears only as Tool Call
  activity.

## Changes

### 2026-09-02 — AF-265 — one implementation PR

- Added: the Metric definitions section above, and a contract suite that asserts
  every row of it across all four filter dimensions against one fixture covering
  two-platform Agents, shared and retired Connections, deleted Agents,
  tool-call-only activity, and the window boundaries.
- Changed: the stats tests seed messages through the Communications Gateway
  rather than `ConversationRepository.upsert_messages`, which has had no
  production caller since AF-271. The read model is now pinned to how messages
  are actually written, and an outbound row is seeded the only way one can
  exist — as a reply to an inbound delivery.
- Fixed: the Agents-over-time series and Tool Call activity dropped an Agent
  from every historical bucket once its Connections were retired, which Agent
  deletion does automatically. With a messaging app selected the panel could
  show messages against an Agent inventory that denied the Agent had existed.
  Historical aggregates now match retired Connections; `count_agents_for_stats`
  keeps the live-only rule, which is correct for a point-in-time count.
- Fixed: Teams is selectable in the messaging-app filter again. The Teams plugin
  stayed registered through AF-271 while `CommunicationPlatform` lost the
  member, so Teams traffic was totalled but could not be isolated.
- Changed: `daily_active_agent_ids_since` narrows by messaging app on the
  message's Connection instead of joining Agent, matching its sibling.
- Changed: the reporting-period control drops Today, Yesterday, Last 7 days,
  Last 30 days, Last week and Last month. The remaining presets — Last hour,
  Last 6/12 hours, This week, This month, This year, Custom range — no longer
  overlap each other. Preset ids never leave the browser, so no API contract
  moved.

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
