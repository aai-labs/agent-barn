# Costs

## Read when

Read before changing spend attribution, the cost sync job, cost healing, cost summaries, deleted-agent handling, cost status labels, or either Costs UI.

## Role in the system

Costs owns a persistent record of every billed LLM call. A CronJob pulls LiteLLM's spend log into the `cost_record` table, attributes each row to an agent and organization, and recovers costs LiteLLM failed to record by asking OpenRouter what it actually charged. The org and platform read surfaces query that table, never LiteLLM.

Reading the proxy at request time — the earlier arrangement — meant a failed query rendered as a confident $0.00, corrected figures had nowhere to live, and server-side filtering and pagination were impossible.

## Invariants

### Storage

- `cost_record` is the source of truth for both read surfaces. Nothing reads LiteLLM at request time.
- Identity columns (`agent_id`, `organization_id`) carry no foreign keys. Cost history is financial record-keeping and stays queryable after the agent or organization is deleted; the display names are captured at write time rather than joined at read time.
- `spend` is `NUMERIC(20,12)` and is never rounded at ingest. Exactness decides whether a row still needs healing. Read models expose it as a float, which only has to be legible.
- Only an allowlist of LiteLLM spend-log fields is stored. Message content, request payloads, caller IP, request tags, end user and session id are deliberately not (see `../adr/2026-07-30-platform-oversight-without-organization-access.md`).
- Rows are unique on `request_id`.

### Sync

- The watermark is derived from `max(occurred_at)`, not stored, and is rewound by an hour on each run because rows land in the spend log after the call they describe. An empty table yields the epoch, which *is* the backfill — there is no first-run special case.
- Spend logs are read in **ascending** time order. Under LiteLLM's default `desc`, a truncated run would store only the newest rows, push the watermark to now, and skip all older history permanently.
- A failed page stops the run rather than skipping it. Pages are ascending, so the watermark already covers everything written and the next run resumes exactly there; skipping ahead would leave a hole nothing revisits.
- Attribution is built from our own `agent` table, keyed by the SHA-256 of each decrypted LiteLLM key. LiteLLM cannot answer it: on production's 40,674 rows its own `agent_id` is NULL on every one and `organization_id` is an empty string on every one. Soft-deleted agents are included, because their keys still appear in historical logs.
- The upsert is guarded on `source = 'litellm_live'`. Each run re-reads the last hour and LiteLLM still reports zero for an already-healed row; an unguarded upsert would revert the recovered figure, re-queue the row, and repeat every 15 minutes without converging.
- Display names are merged with `COALESCE`, never replaced. A later sync can legitimately fail to resolve a hard-deleted agent, and overwriting would erase the only record of who spent the money.

### Healing

- A heal candidate is a successful call with tokens, zero spend, `source = 'litellm_live'`, and an OpenRouter generation id. The predicate matches the partial index exactly.
- The generation-id test is what separates "we lost the cost" from "there was no cost". Failed calls record a UUID request id; treating one as healable would give a failed request fabricated spend.
- Any successful OpenRouter lookup marks the row healed, **including one reporting zero**. A genuinely free generation is still an answer; leaving it untagged would have every future run fetch it again.
- A 404 leaves the row alone. It means "we could not find out", not "this call was free", and writing a zero would assert the latter.
- Healing is unbounded and self-resuming: healed rows stop matching the predicate, so there is no cursor. Only the max-runtime guard bounds a run. Rows are read in batches for memory, and the run loops until the backlog is drained.
- A row a 404 left alone stays a candidate for ever, so the same query keeps returning it. A run therefore remembers what it has already attempted and stops once a batch holds nothing new — otherwise an unresolvable remainder would spend the whole runtime budget re-reading itself every fifteen minutes.

### Reads

- Every aggregate and the row list run through the same predicate, so a stat card and the table beneath it cannot describe different sets of calls.
- The ranked Agent table is not capped, unlike the per-Agent series behind the chart: a line per Agent stops being readable after a handful, but a table has to account for every Agent that spent anything. It keeps the unattributed bucket for the same reason the Organization ranking does.
- On the org surface `organization_id` is pinned by the route and never read from the query string.
- The platform surface has its own routes, service and read model. The org surface must have no code path that can return another organization's name or spend.
- The unattributed bucket stays inside platform totals and is also reported separately. Excluding it would make the platform total exceed the sum of the organizations listed beneath it.
- The OpenRouter balance is reported as one of three states, never as a bare number: `ok` carries the key's remaining credit and its limit, `no_limit` means the key spends without a ceiling, and `unavailable` means the poll failed. The last two used to collapse into a single null, which let "we cannot read it" render the same as "there is nothing to worry about".
- The platform surface warns when a healthy read falls below $5, the threshold the `OpenRouterCreditsLow` alert uses, so the page and the pager cannot disagree. An `unavailable` read warns separately, matching `OpenRouterCreditsUnknown`.

### Authorization and status

- Per-Agent LiteLLM keys are encrypted at rest. A key allocated for a failed, unowned Agent create is deleted; if deletion fails, the key is blocked as a safety fallback.
- Deleting an Agent blocks its LiteLLM key rather than deleting it, preserving key identity and therefore historical attribution.
- Organization cost summaries require the Organization Permission `cost.read`; fixed Organization Owner/Admin roles receive it. An Agent Access Role never authorizes an Organization-wide summary.
- Per-Agent detail requires `cost.read` through the effective Agent Access Role. Agent Viewer, Editor and Owner can read accessible active-Agent costs; Organization Owner/Admin may also read deleted-Agent history.
- Per-Agent detail respects the requested window. It previously read `/key/info`, which is lifetime spend and ignores the date range.
- Per-Agent detail carries its own spend trend, built from the same series query the Organization summary uses under an Agent-pinned filter. It is not read from the summary: that surface requires the Organization-wide `cost.read` an Agent Access Role never grants, so an Agent Viewer or Editor could not load it. The response echoes the resolved window and granularity, because a chart cannot label a bucket without knowing the resolution it was grouped at.
- Cost-facing status is mapped to `active`, `stopped`, `error` or `deleted`; it is not the persisted AgentStatus enum.
- Every platform route requires `require_platform_admin`. Nothing re-scopes by membership, because a platform admin deliberately has none.

## Organization LLM budgets

`../../api/domains/organizations/service.py` owns budget storage and reconciliation;
`../../api/infrastructure/litellm/client.py` owns the remote team/key API calls.

When LiteLLM is configured, every Organization receives a LiteLLM team whose
`team_id` is the Organization UUID. Team identity does not depend on its mutable
name. Both self-service Organization creation and platform user provisioning
attempt team creation after the local transaction commits. A remote failure is
logged without undoing the committed Organization; first Agent key creation
retries provisioning and fails rather than issuing an unassigned key.

The two remote operations are deliberately separate. `ensure_team_exists` only
provisions identity and is what the key-generation path calls: issuing a key must
never re-assert a spend policy its caller was not given. `apply_team_budget` writes
policy and runs only when an administrator sets a budget, or from the drift-repair
sweep. One consequence is that a team created by key generation while the proxy was
unreachable at budget-set time starts uncapped; the recurring CronJob is what closes
that window, which is why reconciliation is scheduled rather than run once at startup.

The Organization row is authoritative and LiteLLM is a projection of it. A budget is
stored first and pushed second, so a proxy failure surfaces as `502` with the
setting retained for the next reconciliation rather than silently discarded. Only
changed fields are written: an update reschedules the renewal date, so re-sending an
unchanged policy would quietly move every Organization's window. No reconciliation
writes `spend` or resets accumulated usage. Removing the amount clears the limit and
the renewal schedule.

Budgets are platform-administered. An Organization has no route to read or change
its own ceiling — a cap a customer can raise is not a cost control. Teams are
retained on Organization deletion for historical attribution; their Agent keys have
already been blocked by Agent deletion.

Agents retain individual virtual keys and attribution metadata, and new keys include
`team_id`. Keys issued before an Organization had a team carry none, so a limit does
not bind them until they are enrolled — `enroll_llm_keys` attaches them and refuses to
move a key that already belongs to a different team. Coverage is read live rather than
cached, because a key detached by hand would make a stored answer claim coverage the
Organization does not have, and the budget controls stay hidden until every Agent is
covered so a limit is never set over Agents it would silently miss.

LiteLLM enforces its own recorded spend, independently of `cost_record` and
OpenRouter cost healing. That figure is known to sit slightly below the truth —
healing recovers costs LiteLLM booked as zero, into our table only, and cannot write
them back — so a cap binds marginally late in real dollars and always fails open,
never closed. Historical requests made before team attachment are not retroactively
charged. In-flight requests can exceed any cap. This is a proxy spend cutoff, not an
exact provider-invoice ceiling, and only calls using these LiteLLM Agent keys count.
A budget rejection does not stop the Agent container or suspend the Organization;
model calls fail until the limit renews or is raised or removed. Both runtimes'
in-pod LLM proxy rewrites that rejection before the runtime sees it, so the person
talking to the Agent is told the Organization has reached its limit rather than
shown a raw error naming an internal team id. It is matched on the error body rather
than the status, because the same 400 covers malformed requests and unknown models
that must keep their own errors.

## Operational

- The CronJob runs every 15 minutes under `concurrencyPolicy: Forbid`. `COST_SYNC_MAX_RUNTIME_SECONDS` must stay below the schedule interval: an overrunning pass does not overlap, it silently costs the next tick.
- Unlike the event reconciler, this job talks to the Kubernetes API — it reads the LiteLLM master key from the `litellm` Secret. It needs the service account, `K8S_NAMESPACE`, `K8S_KUBECONFIG_PATH` and the mounted kubeconfig, or it fails on first run with `Secret 'litellm' not found`.
- `/spend/logs/v2` needs the LiteLLM **master** key; the virtual key in `litellmApiKeySecretName` cannot authenticate it.
- The entrypoint is `python -c "from api.domains.costs.sync import main; main()"`, never `python -m`. Running the module as `__main__` re-imports it under a second name, so its `CostSynchronizer` no longer matches the class AppModule's provider bound.
- On first release in any deployment, historical totals **rise** as healing recovers spend LiteLLM dropped. That is the fix working, not a regression.
- The summary line logs the attributed/unattributed ratio and the heal backlog. A rising unattributed count means key decryption or agent bookkeeping has drifted, not that spend grew.

## Known gaps

- Cache-read token tracking is not implemented. Cached input tokens bill at roughly 12–20% of fresh input and cache writes at 120–125%, and neither LiteLLM's spend log nor our table distinguishes them.
- Alerting, budget caps, and per-user or per-conversation attribution are out of scope.
- The cost-per-call histogram's cheapest band also holds unhealed rows, which record $0 until the healing job reaches them.

## Boundaries

Agents own LiteLLM key creation, encryption, deletion blocking, and lifecycle status. The LiteLLM and OpenRouter infrastructure clients own remote API behavior. Costs owns the persisted record, attribution, healing, and aggregation. Conversation and Tool Call data do not feed cost calculation. Agent Activity reads `cost_record` for its own per-Agent surface and annotates it with message timing; it owns no table and changes no figure here (see [`agent-activity.md`](agent-activity.md)).

## Source map

| Concern                       | Authoritative source                  |
| ----------------------------- | ------------------------------------- |
| Table and response contracts  | `../../api/domains/costs/models.py`         |
| Persistence and aggregation   | `../../api/domains/costs/repository.py`     |
| Sync and healing job          | `../../api/domains/costs/sync.py`           |
| Tunables                      | `../../api/domains/costs/constants.py`      |
| Org reads                     | `../../api/domains/costs/service.py`        |
| Platform reads                | `../../api/domains/costs/platform_service.py` |
| HTTP routes                   | `../../api/domains/costs/routes.py`, `../../api/domains/costs/platform_routes.py` |
| LiteLLM client                | `../../api/infrastructure/litellm/`         |
| OpenRouter client             | `../../api/infrastructure/openrouter/`      |
| Agent key lifecycle           | `../../api/domains/agents/service.py`       |
| CronJob                       | `../../helm/agentbarn-api/templates/cost-sync-cronjob.yaml` |
| Org budget storage and policy | `../../api/domains/organizations/service.py`, `../../api/domains/organizations/routes.py` |
| Org budget reconciler         | `../../api/domains/organizations/llm_budget_reconciliation.py` (`make reconcile-llm-budgets`), `../../helm/agentbarn-api/templates/llm-budget-reconciliation-cronjob.yaml` |
| Org budget UI                 | `../../ui/src/features/organizations/components/llm-budget-card.tsx`, `../../ui/src/features/organizations/components/llm-budget-banner.tsx` |
| Threshold alerts              | `../../api/domains/organizations/llm_budget_alerts.py` (`make run-llm-budget-alerts`), `../../helm/agentbarn-api/templates/llm-budget-alerts-cronjob.yaml` |
| Budget notification email     | `../../api/domains/organizations/event_handlers.py`, `../../api/infrastructure/email/templates/organization-budget-template.mjml` |
| Agent-facing rejection        | `../../api/domains/agents/scripts/hermes/healthz-server.py`, `../../api/domains/agents/scripts/openclaw/healthz-server.js` |
| UI schemas, hooks, and charts | `../../ui/src/features/costs/`              |
| Local fixtures                | `../../api/scripts/seed_cost_fixtures.py` (`make seed-costs`) |
| Investigation and evidence    | `../plans/AF-281-cost-tracking-findings.md` |
| Tests                         | `../../api/tests/unit/test_cost_sync.py`, `../../api/tests/integration/test_costs.py`, `../../api/tests/integration/test_platform_costs.py`, `../../ui/tests/e2e/costs.spec.ts`, `../../ui/tests/e2e/platform-costs.spec.ts`, `../../api/tests/unit/test_organization_llm.py`, `../../api/tests/integration/test_organization_llm.py`, `../../ui/tests/e2e/organization-llm-budget.spec.ts` |

## Change impact

Changing the sync or heal predicates changes what is recorded as money, so cover them in unit tests before touching the job. Changing attribution affects agent key lifecycle, deleted-agent behavior, and the unattributed bucket. Changing the schedule requires rechecking `COST_SYNC_MAX_RUNTIME_SECONDS`. Status changes require checking both persisted AgentStatus and the cost-facing mapped labels.
