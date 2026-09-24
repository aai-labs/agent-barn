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

Three limits, each enforced by LiteLLM, all sharing the Organization's renewal window:

| Limit | Set by | Stored on | Enforced on |
| --- | --- | --- | --- |
| Spend Ceiling | Platform Administrator | `organization.llm_budget_usd` (never NULL) | — |
| The Organization's own limit | Owners and Admins (`llm_budget.manage`) | `organization.llm_own_budget_usd` (NULL follows the ceiling) | The Organization's team: `own ?? ceiling` |
| Default Agent limit | Owners and Admins | `organization_agent_settings.default_agent_llm_budget_usd` (NULL follows `AGENT_DEFAULT_LLM_BUDGET_USD`) | — |
| An Agent's own limit | Owners and Admins | `agent.llm_budget_usd` (NULL follows the default) | The Agent's key: `min(own ?? default, Organization limit)` |

`../../api/domains/organizations/llm_budget_service.py` owns the ceiling and the
Organization's own limit; `../../api/domains/agents/llm_budget.py` owns Agent limits;
`../../api/domains/agent_settings/service.py` owns the default Agent limit;
`../../api/infrastructure/litellm/client.py` owns the remote team/key API calls.

**Nobody is uncapped.** A new Organization starts at
`ORGANIZATION_DEFAULT_LLM_BUDGET_USD` whichever path creates it, and the migration
that introduced these limits gave every existing Organization without a ceiling that
default. The ceiling can be changed but never cleared; "no practical limit" is a very
large amount. A new Agent's key is issued with its limit already on it.

**Lower limits never exceed higher ones.** Asking for an Organization limit above the
ceiling, or an Agent or default Agent limit above the Organization's, is refused
(`400`) rather than silently stored as something else. Lowering a limit instead pulls
everything beneath it down with it: a lower ceiling lowers the Organization's own
limit, and a lower Organization limit lowers the default and every Agent limit above
it. Each of those is recorded as its own change Event whose `reason` says it followed
from another change. The sum of Agent limits may exceed the Organization's; the
team budget still binds.

**One window.** Windows are restricted to `1d`, `7d` and `30d` because LiteLLM snaps
those to calendar boundaries — next midnight, next Monday, the 1st of the month — no
matter when a budget was set. The team and every Agent key therefore renew at the
same moment; any other `Nd` would renew N days after it was set and drift. `30d` is a
calendar month, not a 30-day interval.

When LiteLLM is configured, every Organization receives a LiteLLM team whose
`team_id` is the Organization UUID. Creating an Organization, through either path that
does, pushes its team with the limit already on it. A remote failure is logged
without undoing the committed Organization; first Agent key creation provisions the
team again — with the Organization's limit, so it is never uncapped in between — and
fails rather than issuing an unassigned key. `ensure_team_exists` never writes policy
over an existing team: issuing a key must not re-assert a policy its caller was not
given.

Rows are authoritative and LiteLLM is a projection of them. A limit is stored with
its change Event first and pushed second, so a proxy failure surfaces as `502` with
the setting retained. Only changed fields are written, because re-sending a window
reschedules the renewal date. When an Organization-wide change moves many Agents,
only the keys whose resolved limit actually changed are rewritten; a key that cannot
be updated is left to reconciliation rather than failing a change already saved. The
reconciliation CronJob pushes every team and every Agent key, and also re-applies the
"never above the Organization" rule, so an Agent limit left above a lowered
Organization limit by an interrupted request is brought back within it.

Keys issued before an Organization had a team carry none, so the team budget does not
bind them until they are enrolled — `enroll_llm_keys` attaches them and refuses to move
a key that already belongs to a different team. A Platform Administrator sees which
Agents are not covered, by name, beside the ceiling controls.

Owners and Admins manage every level beneath the ceiling in one place, Settings →
Spend limits: the Organization's own limit, the default Agent limit, and a table of
each Agent's limit and where it comes from (`GET
/organizations/{id}/agents/llm-budgets`, Organization-wide `cost.read`). Lowering the
Organization's limit shows what it will pull down before it is saved. The Costs page
shows spend against the limit read-only, and each Agent's own limit is also set from
that Agent's configuration.

Threshold alerts cover both levels. The Organization's go to its Owners and Admins, and
to Platform Administrators when it is exhausted. An Agent's go to its creator and
Owners — the same people told about its lifecycle — and never to Platform
Administrators, since one Agent running out is its Organization's business.

LiteLLM enforces its own recorded spend, independently of `cost_record` and
OpenRouter cost healing. That figure is known to sit slightly below the truth —
healing recovers costs LiteLLM booked as zero, into our table only, and cannot write
them back — so a cap binds marginally late in real dollars and always fails open,
never closed. Historical requests made before team attachment are not retroactively
charged. In-flight requests can exceed any cap. This is a proxy spend cutoff, not an
exact provider-invoice ceiling, and only calls using these LiteLLM Agent keys count.
A rejection does not stop the Agent container or suspend the Organization; model
calls fail until the limit renews or is raised. Both runtimes' in-pod LLM proxy
catches the rejection before the runtime sees it — matched on the error body, since
the proxy has answered with `400`, `429`, and `422` on releases after the pinned one,
and those statuses also carry malformed requests and ordinary rate limits that must
keep their own errors. It answers the runtime with `402` and a clean message, because
both runtimes retry a `429` as a rate limit indefinitely and the person chatting
would never hear back.

Neither runtime carries the reason out faithfully: OpenClaw replaces the proxy's
message with its own billing text, and Hermes aborts the turn. So the proxy also
records the refusal in the container (`/tmp/agentbarn-llm-terminal-error.json`), and
the Communications adapter in the same container reports a turn that fails after it
as `SPEND_LIMIT_REACHED`. Communications turns that code into a terminal,
non-retried failure whose notice reads "This agent has reached its model spend
limit…": shown under the message in web chat, and posted as the failure notice on
Slack, Telegram, Discord and Teams. The message is the same whichever limit ran out.

## Operational

- The CronJob runs every 15 minutes under `concurrencyPolicy: Forbid`. `COST_SYNC_MAX_RUNTIME_SECONDS` must stay below the schedule interval: an overrunning pass does not overlap, it silently costs the next tick.
- Unlike the event reconciler, this job talks to the Kubernetes API — it reads the LiteLLM master key from the `litellm` Secret. It needs the service account, `K8S_NAMESPACE`, `K8S_KUBECONFIG_PATH` and the mounted kubeconfig, or it fails on first run with `Secret 'litellm' not found`.
- `/spend/logs/v2` needs the LiteLLM **master** key; the virtual key in `litellmApiKeySecretName` cannot authenticate it.
- The entrypoint is `python -c "from api.domains.costs.sync import main; main()"`, never `python -m`. Running the module as `__main__` re-imports it under a second name, so its `CostSynchronizer` no longer matches the class AppModule's provider bound.
- On first release in any deployment, historical totals **rise** as healing recovers spend LiteLLM dropped. That is the fix working, not a regression.
- The summary line logs the attributed/unattributed ratio and the heal backlog. A rising unattributed count means key decryption or agent bookkeeping has drifted, not that spend grew.

## Known gaps

- Cache-read token tracking is not implemented. Cached input tokens bill at roughly 12–20% of fresh input and cache writes at 120–125%, and neither LiteLLM's spend log nor our table distinguishes them.
- Per-user or per-conversation attribution is out of scope.
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
| Org budget storage and policy | `../../api/domains/organizations/llm_budget_service.py`, `../../api/domains/organizations/routes.py` |
| Agent spend limits            | `../../api/domains/agents/llm_budget.py`, `../../api/domains/agents/routes.py`, `../../api/domains/agent_settings/service.py` (default Agent limit) |
| Org budget reconciler         | `../../api/domains/organizations/llm_budget_reconciliation.py` (`make reconcile-llm-budgets`), `../../helm/agentbarn-api/templates/llm-budget-reconciliation-cronjob.yaml` |
| Spend limit UI                | `../../ui/src/features/spend-limits/` (Settings → Spend limits: organization limit, default Agent limit, Agent limits table), `../../ui/src/features/agents/components/agent-spend-limit-settings.tsx`, `../../ui/src/features/organizations/components/llm-budget-card.tsx` (ceiling), `../../ui/src/features/organizations/components/spend-limit-status.tsx` and `llm-budget-banner.tsx` (Costs page) |
| Threshold alerts              | `../../api/domains/organizations/llm_budget_alerts.py` (`make run-llm-budget-alerts`), `../../helm/agentbarn-api/templates/llm-budget-alerts-cronjob.yaml` |
| Budget notification email     | `../../api/domains/organizations/event_handlers.py`, `../../api/domains/agents/event_handlers.py` (Agent limits), `../../api/infrastructure/email/templates/organization-budget-template.mjml` |
| Agent-facing rejection        | `../../api/domains/agents/scripts/hermes/healthz-server.py`, `../../api/domains/agents/scripts/openclaw/healthz-server.js` |
| UI schemas, hooks, and charts | `../../ui/src/features/costs/`              |
| Local fixtures                | `../../api/scripts/seed_cost_fixtures.py` (`make seed-costs`) |
| Investigation and evidence    | `../plans/AF-281-cost-tracking-findings.md` |
| Tests                         | `../../api/tests/unit/test_cost_sync.py`, `../../api/tests/integration/test_costs.py`, `../../api/tests/integration/test_platform_costs.py`, `../../ui/tests/e2e/costs.spec.ts`, `../../ui/tests/e2e/platform-costs.spec.ts`, `../../api/tests/unit/test_organization_llm.py`, `../../api/tests/integration/test_organization_llm.py`, `../../api/tests/unit/test_spend_limits.py`, `../../api/tests/integration/test_spend_limits.py`, `../../api/tests/integration/test_spend_limits_migration.py`, `../../ui/tests/e2e/organization-llm-budget.spec.ts`, `../../ui/tests/e2e/spend-limits.spec.ts` |

## Change impact

Changing the sync or heal predicates changes what is recorded as money, so cover them in unit tests before touching the job. Changing attribution affects agent key lifecycle, deleted-agent behavior, and the unattributed bucket. Changing the schedule requires rechecking `COST_SYNC_MAX_RUNTIME_SECONDS`. Status changes require checking both persisted AgentStatus and the cost-facing mapped labels.
