# Agent Activity

## Read when

Read before changing the Agent Activity tab, wake grouping, trigger attribution, or any per-Agent read over `cost_record`.

## Role in the system

Activity answers what one Agent has been *doing*, using the rows Costs already stores. Costs answers how much was spent; the spend trend on the About tab draws a smooth curve whether an Agent is serving a team or looping on a timer, so an Agent burning tokens with nobody talking to it looks exactly like one doing its job.

The unit here is a **wake** — a burst of model calls close together in time, which is the piece of work a person recognises. Each wake carries its own totals, the spread of prompt sizes inside it, and a **trigger**: whether a person messaged the Agent just before it started, or nothing did.

Three reads nest, all driven by the same window, so drilling in is only ever a narrower window: a summary over the whole range, the wakes inside it, and the individual billed calls inside those.

## Invariants

- Every usage figure comes from `cost_record`. Activity owns no table and writes nothing; runtime evidence is read separately through Agents.
- A wake is a maximal run of one Agent's calls where no two consecutive calls are more than `WAKE_GAP_SECONDS` apart. The grouping is a Postgres window function over `occurred_at`, not application code, so the wake list, the per-trigger totals and the cadence all describe the same bursts.
- A wake is `USER` when an inbound `agent_chat_message` for that Agent falls within `[started_at - USER_LEAD_SECONDS, ended_at]`, and `BACKGROUND` otherwise. Only direction and occurrence time are read; message content never is.
- The trigger is inferred, not reported. The runtime does not tell us what started a turn, so `BACKGROUND` means "no inbound message was recorded for this Agent around then" — a cron, a heartbeat, or the Agent's own follow-up are indistinguishable from each other here.
- A call's trigger is its wake's trigger. The calls list filters through the same wake grouping rather than re-deriving a per-call answer, so the two views cannot disagree about which calls ran without a person.
- The summary always reports both triggers, including at zero. An Agent whose user-triggered count is zero is the case the tab exists to surface, and a missing row would hide it.
- `wake_cadence_seconds` is the median gap between consecutive wake starts, and is null below two wakes. The median is a signal, not proof of periodicity or a claim about which schedule.
- Bucket timestamps are returned as UTC-aware instants. `date_trunc` over a naive timestamp yields a naive one, which a client would render in local time and slide off the boundary the server grouped on.
- Quiet buckets are returned at zero rather than omitted, so a gap in activity reads as a gap.
- Reads require **both** `cost.read` and `activity.read` through the effective Agent Access Role, because the response mixes billed-call figures with message-derived attribution. Every system Agent Access Role grants both, so the pair costs no reader access it would otherwise have.
- Organization Owners and Admins hold implicit Agent Owner authority, so a permission this surface requires can only be withheld from someone whose authority comes from an Agent Access Role. Denial tests must be written that way.

## Boundaries

Costs owns the record, its attribution to an Agent, healing and the money. Conversations own message persistence. Activity owns only the read shapes above and reads both without writing either. It does not feed cost calculation, and it adds no field to the cost read models the Platform surface shares.

## Known gaps

- Attribution cannot name *which* schedule woke an Agent. Distinguishing a named cron from a periodic heartbeat needs the runtime to tag its requests, which is a separate change to the runtime and the sync allowlist (see `../adr/2026-07-30-platform-oversight-without-organization-access.md` for why the allowlist is deliberate).
- A background wake that a person happened to message during is read as user-triggered. The lead window is deliberately short, but the overlap is real.
- Wake grouping scans the window on every read. There is no materialised rollup; `ix_cost_record_agent_occurred` is what keeps it bounded.

## Source map

| Concern                    | Authoritative source                                      |
| -------------------------- | --------------------------------------------------------- |
| Read contracts and tunables | `../../api/domains/activity/models.py`                    |
| Wake grouping and queries   | `../../api/domains/activity/repository.py`                |
| Authorization and assembly  | `../../api/domains/activity/service.py`                   |
| HTTP routes                 | `../../api/domains/activity/routes.py`                    |
| UI tab                      | `../../ui/src/features/agents/components/activity-tab.tsx`, `../../ui/src/features/agents/components/activity-tables.tsx` |
| UI hooks and schemas        | `../../ui/src/features/agents/hooks/use-agent-activity.ts`, `../../ui/src/features/agents/schemas.ts` |
| Tests                       | `../../api/tests/integration/test_agent_activity.py`, `../../ui/tests/e2e/agent-activity.spec.ts` |

## Change impact

Changing the wake gap or the lead window changes what every figure on the tab means, so both live in `models.py` beside the trigger enum and are covered by integration tests that seed calls at explicit offsets. Adding a dimension to these reads is an authorization and data-classification decision, not a free consequence of it being available in `cost_record`.

## Related decisions

- [`2026-07-30-platform-oversight-without-organization-access.md`](../adr/2026-07-30-platform-oversight-without-organization-access.md)

## Runtime investigation

The Activity tab also presents [Agent runtime diagnostics](agents.md#runtime-diagnostics)
independently of the usage window. It shows termination and previous-container log
evidence even when no model calls occurred. Diagnostic fetch failures have a local
retry and do not hide usage. This uses the Agents domain and `activity.read`; the
Activity cost endpoints still require both `activity.read` and `cost.read`.

`last_call_at` is the latest recorded call in the selected half-open usage window,
or null when empty. It is returned as a UTC instant and is not proof that billing
has stopped: records can arrive late. Runtime observations are current, not a
historical snapshot of the selected usage range. No automatic causal link is made
between cost, prompt size, termination, or workspace migration.

Trigger labels describe nearby *recorded* messages. Missing telemetry can look
like background work, and median wake spacing does not prove periodicity or name
a cron/heartbeat. Prompt distributions suggest context repetition but do not
identify its contents. Changing the date range clears the previous drill-down.
