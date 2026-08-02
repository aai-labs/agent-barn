# AF-235 remaining Platform Management tasks

Status: Draft backlog — create Jira tasks, then remove this file
Parent epic: [AF-235](https://aai-labs.atlassian.net/browse/AF-235)
Defined after sharpening [AF-237](https://aai-labs.atlassian.net/browse/AF-237)

AF-237 owns self-service Organization creation and the narrow Platform Administrator authority boundary. Its delivered Platform View slice includes allowlisted Organization/user identity and membership detail projections; the broader independently deliverable oversight tasks below remain under AF-235.

## Task 1 — Suspend and reactivate Organizations with asynchronous Agent cleanup

### Goal

Allow Platform Administrators to suspend and reactivate Organizations without granting Organization View authority or coupling the security boundary to Kubernetes availability.

### Acceptance criteria

- Organization has an `ACTIVE` or `SUSPENDED` Organization Status.
- Suspension and reactivation are Platform Administrator operations requiring user-session credentials and a trimmed, non-empty reason of at most 1,000 characters.
- Repeating a transition that would not change Organization Status returns `409` and creates no Domain Event or Security Audit Record.
- Suspension atomically:
  - marks the Organization `SUSPENDED`;
  - records the reason;
  - stages an Organization-scoped suspension Domain Event;
  - immediately denies Organization-scoped product requests, Agent starts, runtime Ingest, webhooks, and Organization background work.
- An idempotent Event Handler stops the Organization's running Agent resources asynchronously. Suspension succeeds even when runtime cleanup is delayed or temporarily fails.
- Cleanup is tracked as `PENDING`, `RUNNING`, `COMPLETE`, or `FAILED`; failure counts are available as safe Platform Oversight Data.
- Reactivation is rejected until cleanup is `COMPLETE`.
- Reactivation restores Organization access but never restarts Agents automatically.
- Failed cleanup can be retried by a Platform Administrator; retries create operational Security Audit Records without inventing a new human reason.
- Suspended Organizations remain visible but disabled in Members' Organization selectors, with a clear badge and a dedicated suspension screen for bookmarked URLs. The Platform Administrator's reason is not shown to ordinary Members.
- Platform UI exposes suspend, retry-cleanup, and reactivate actions with the required confirmation and reason input.
- Tests cover transition preconditions, immediate access/Ingest/webhook denial, asynchronous cleanup and retry, reactivation gating, no automatic restart, audit events, and selector behavior.

### Related decisions

- `docs/adr/2026-07-30-suspend-organizations-before-runtime-cleanup.md`
- `docs/adr/2026-07-30-explicit-platform-and-organization-event-scopes.md`

### Out of scope

- Organization deletion.
- Impersonation.
- Exposing tenant content or raw runtime logs in Platform View.

## Task 2 — Build the unified Platform Security Audit explorer

### Goal

Turn the Security Audit Record projection into the single durable, searchable Platform View surface for security-relevant Platform- and Organization-scoped actions.

### Acceptance criteria

- The `security_audit.projection` Event Handler persists immutable, idempotent Security Audit Records for all safely mapped security event versions, including:
  - Platform Privilege grants and revocations;
  - Organization suspension, cleanup retry, and reactivation;
  - Organization Role changes;
  - Agent Access grants and revocations;
  - Agent General Access changes.
- Records retain typed Event Scope, action, actor and subject identities, bounded display snapshots, timestamp, resulting state/outcome, and an applicable human reason.
- Records survive deletion of their Organization, User, Membership, Agent, or other live subject and remain visibly marked as historical/deleted when known.
- Records are retained indefinitely until a separately approved retention policy replaces that default.
- Platform Administrator APIs provide cursor-paginated filtering by action type, Event Scope, actor, Organization, subject, outcome, and date range.
- Search supports bounded reason and identity fields without querying raw Domain Event payloads.
- `/dashboard/platform/audit` provides the unified searchable/filterable audit page.
- Resource detail pages may link to pre-filtered audit results rather than embedding separate audit timelines.
- Only user-session-authenticated Platform Administrators can query Security Audit Records.
- Adding a new event to the explorer requires an explicit safe display mapping; event registration alone does not expose it.
- Tests cover projection idempotency, deletion survival, filtering/search/pagination, authorization, snapshot safety, and unknown/unmapped event behavior.

### Related decisions

- `docs/adr/2026-07-30-explicit-platform-and-organization-event-scopes.md`
- `docs/adr/2026-07-31-retain-security-audit-records-across-product-deletion.md`
- `docs/adr/2026-07-30-platform-oversight-without-organization-access.md`

### Dependencies

- AF-237's Platform-scoped Domain Event and minimal Security Audit Record foundation.
- The Organization suspension task for its event types.

### Out of scope

- Editing or deleting Security Audit Records.
- Raw Outbox Message or Event Delivery administration.
- Configurable retention and archival.

## Task 3 — Add cross-Organization Platform Oversight dashboards

### Goal

Give Platform Administrators read-only, explicitly allowlisted cross-Organization oversight without an Active Organization, synthetic Membership, or Organization-scoped endpoint access.

### Acceptance criteria

- Dedicated Platform APIs and read models expose only allowlisted Platform Oversight Data; Organization-scoped DTOs and routes are not reused.
- Platform Organization list/detail includes:
  - ID, name, description, Organization Status, creation/update timestamps;
  - immutable Organization Creator and current Organization Owner identities;
  - accepted Member count and pending invitation count;
  - accepted and pending Membership details with status and Organization Role;
  - active/deleted Agent counts;
  - bounded activity, model-usage, and platform-borne cost summaries.
- Platform user list/detail includes identity, email verification state, Platform Privilege state, timestamps, and Organization Memberships with Organization details, role, and accepted/pending status.
- Platform Agent list/detail includes Organization, identity, creator, lifecycle status and last transition, Runtime, chat Platform, current Configured Model, and optional inclusion of deleted Agents.
- Agent lists exclude deleted Agents by default and provide an `include_deleted` filter. Deleted Agent details preserve historical activity, model usage, and cost attribution without exposing deleted configuration or tenant content.
- Safe activity statistics support 7-, 30-, and 90-day periods, defaulting to 30 days:
  - last activity timestamp;
  - inbound/outbound message counts;
  - Tool Call totals by pending/success/error;
  - Tool Call success rate and average duration;
  - lifecycle status and last status change.
- Activity oversight excludes sender, channel, and session identities; message content; Tool names, arguments, results, and error content; and logs.
- Model oversight distinguishes:
  - Configured Model counts for current active Agents;
  - Observed Model Usage from LiteLLM for the selected period, including participating Agent count and prompt/completion/total tokens.
- Cost oversight includes:
  - Platform total and time series;
  - cost and tokens by observed model;
  - Organization total, time series, and Agent breakdown;
  - Agent total, time series, and model breakdown.
- Cost is not attributed to users.
- Platform View pages provide Organization, user, Agent, activity, model, and cost list/detail/drill-down experiences while never establishing an Active Organization.
- The Organization selector remains Membership-based for every user, including Platform Administrators; Platform Privilege never adds all Platform Organizations to Organization View navigation.
- Tests cover field allowlists, forbidden sensitive fields, cross-Organization reads, Platform Administrator authorization, Membership-independent oversight, pagination/filtering, deleted-Agent handling, reporting periods, and cost/model aggregation.

### Explicitly excluded data

- Conversation or message content.
- Tool names, inputs, results, and error content.
- Logs, prompts, templates, Skills, and configuration payloads.
- Credentials, Agent Secrets, and raw Telemetry Events.

### Related decision

- `docs/adr/2026-07-30-platform-oversight-without-organization-access.md`

### Dependencies

- AF-237's narrow Platform Administrator gate.
- The Organization suspension task for Organization Status and cleanup summaries.

### Out of scope

- Organization-scoped mutation.
- Impersonation.
- User-attributed cost.
