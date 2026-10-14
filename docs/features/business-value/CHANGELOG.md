# Business value measurement — change log

Status: Active
Epic: Business value measurement
Related context: [Activity and Ingest](../activity-and-ingest.md), [Agent Activity](../agent-activity.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [classification ADR](../../adr/2026-09-25-classify-business-actions-at-ingest.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: pre-flight evidence and real Hermes and OpenClaw result fixtures. Also delivered: the code-owned aai-cli command catalogue in `api/domains/business_value/catalogue.py`, with a drift test against the bundled references.
- Also delivered: the pure classifier `classify(tool_call)` in `api/domains/business_value/classifier.py`.
- Also delivered: the `business_action` table (migration `39ea6a8e2fe4`) and `BusinessActionRepository.record_in_session`.
- Also delivered: Ingest records Business Actions for every completed shell Tool Call and exports `agentbarn_business_actions_total`. The feature doc is [`../business-value.md`](../business-value.md).
- Also delivered: the operator backfill (`make backfill-business-actions`) for Tool Calls stored before Ingest recorded Business Actions.
- Also delivered: the `organization_value_settings` and `organization_outcome_minutes` tables (migration `1045836844da`).
- Also delivered: the `organization.value_settings.changed` Domain Event, registered and projected to the security audit and emitted by the value settings API.
- Also delivered: the pure valuation rules in `api/domains/business_value/service.py` (effective minutes, value, the value-to-spend ratio, and write categories).
- Also delivered: `ValueSettingsRepository`, which saves value settings and stages `organization.value_settings.changed` in one transaction.
- Also delivered: `GET` and `PUT /organizations/{organization_id}/value-settings`. The feature doc's [Value settings](../business-value.md#value-settings) section is the contract.
- Also delivered: the scoped Business Action aggregate reads the value KPI needs.
- Also delivered: `GET /organizations/{organization_id}/value`, the Organization value KPI. The feature doc's [Organization value](../business-value.md#organization-value) section is the contract.
- Also delivered: gog (Google Workspace) commands are classified as Business Actions and valued like aai-cli ones. See the feature doc's [gog commands](../business-value.md#gog-commands) section.
- Also delivered: review fixes. Value-settings saves are serialized under a row lock and record what they actually replaced, and the per-bucket Business Action query no longer builds an unused bucket spine.
- Also delivered: `GET /organizations/{organization_id}/value/activity`, the Organization activity KPI. The feature doc's [Organization activity](../business-value.md#organization-activity) section is the contract. It rests on `ValueActivityRepository` and the two indexes of migration `45bcefcb0749`.
- Also delivered: the KPIs page route and its Owner/Admin navigation entry (AF-348). The feature doc's [KPI dashboard](../business-value.md#kpi-dashboard) section is the contract.
- Also delivered: the KPIs page's date range and six headline tiles, read from `GET /value` and `GET /value/activity` (AF-348).
- Also delivered: the KPIs page's trend chart, with "Value vs spend" and "Requests" tabs (AF-348).
- Also delivered: the KPIs page's per-Agent table and footnotes (AF-348).
- Also delivered: the KPIs page's empty state and loading skeletons (AF-348).
- Also delivered: the KPIs page's value settings Sheet, which reads, edits, validates, resets, and discards (AF-348).
- Also delivered: saving value settings from the KPIs page, which refreshes the value figures (AF-348).
- Also delivered: the AF-348 KPIs dashboard, verified end to end on local k3d against the real API and database.
- Also delivered: the backfill runs as a Job on every install and upgrade, so Organizations with spend from before classification was deployed get the value that matches it.
- In transition: nothing.
- Next: none. Every planned slice of the epic is delivered.
- Blockers: the product owner has not signed off the default minutes per Outcome Type. They are placeholders until then, and every value figure inherits them.

## Slice history

### 2026-10-08 — Credential gateway staging merge

- Changed: removed the retired Zoho Mail `email messages list/get` paths from the aai-cli catalogue, matching the credential-gateway branch's shipped skill bundle. These were reads and contributed no saved minutes; the remaining catalogue and drift coverage are preserved.

### 2026-10-08 — Backfill runs on every deploy

Why:
- Value per dollar counted spend from before classification was deployed but no value for it, so the ratio was too low for existing Organizations. Live on local k3d: deleting an Organization's only Business Action took its ratio from $645.28 to $0.00 per $1, and the backfill restored $645.28.
- The documented `kubectl exec deploy/agentbarn-api -c api` backfill OOM-killed the API container (512Mi) on local k3d. Client clusters cannot be reached to run it by hand at all.

Changed:
- `helm/agentbarn-api/templates/business-action-backfill-job.yaml`: a plain Job, `<release>-business-action-backfill-<revision>`, with `worker.resources`, `backoffLimit: 2`, and `businessValue.backfill.activeDeadlineSeconds` (3600). `businessValue.backfill.enabled` defaults to `true`.
- `BACKFILL_BATCH_SIZE` drops from 500 to 50.
- `operations.md`, `business-value.md`, and the RBAC brief's background-work exception now describe a deploy-run Job instead of `kubectl exec`.

Verification, local k3d:
- With a throwaway chart holding one plain Job, `helm upgrade --install --wait --timeout 30s` returned in about 1s under Helm 4.2.1 and Helm 3.18.4, for both a running and a failing Job. So did `helmfile sync --wait` (helmfile 1.7.1). The next upgrade deleted the previous revision's Job and its pod, including one still running.
- `helm template` renders the Job with the release's image, pull secret, `agentbarn-api` secret, and resources, and renders nothing when `businessValue.backfill.enabled=false`. `helm lint` passes.
- The rendered Job against the local database:
  1. After the "KPI note check" Business Action was deleted, `GET /value` returned `value_to_spend_ratio` 0.0.
  2. The Job logged `scanned=1 recorded=1 removed=0 failed=0`, and the ratio returned to 645.28. The API pod's restart count stayed at 2.
  3. A second run logged `recorded=0`.
- Memory, with 600 extra completed `terminal` Tool Calls of about 1MB result each (572MB in total):
  - At batch size 500, all three attempts were OOMKilled. The Job failed, and the API was unaffected.
  - At batch size 50, it completed with `scanned=601 failed=0`. Peak RSS was 314MB, against 171MB on the empty table.
  - The seeded rows were then deleted.
- `test_business_action_backfill.py`: 10 passed.

Not verified:
- The size of real stored Tool Call results on staging or production. Batch size 50 stays under 512Mi up to about 2.5MB of result per Tool Call on average, from the figures above.

### 2026-10-07 — AF-348 — Calculation hints and Value settings modal

- Delivered: clickable calculation hints on all six KPI cards, with estimated-hours wording and an explanation of each Value vs spend interval. They work with keyboard and touch as well as mouse.
- Changed: Value settings now opens a centered modal with explanatory copy, a scrollable form, and a visible action footer. Validation, reset, save, and discard confirmation keep their existing contracts.
- Fixed: a settings query refresh no longer changes the editing baseline and sends an untouched field back to an older value. Failed background reads preserve the draft.
- Fixed: a failed KPI refetch clears that source's stale Agent-table figures, matching the tiles and chart.
- Verification: browser regression probes reproduced both state failures before these changes; lint, typecheck, production build, and the KPI/Costs/navigation browser checks pass. Focused coverage includes calculation guidance, desktop/mobile modal layout, reconnect, and retry behavior. Removing the failed-refetch guard makes its regression test fail at the stale-value assertion.
- Follow-up: no API, schema, migration, or release changes.

### 2026-10-02 — AF-348 — Coverage wording for the handled rate and response time

Changed:
- The Handled tile's hint reads "based on X of Y requests routed through Agent Barn". The footnote says natively connected channels count as Requests but are not timed. Neither names channels any more.
- `business-value.md` no longer lists the deployed native platforms. It points to `operations.md` instead.

Why:
- The ticket asked for "Web Chat and Email only". Which channels are covered depends on each environment's `COMMUNICATIONS_NATIVE_PLATFORMS`, so fixed channel names can be false.
- Live on local k3d, with `COMMUNICATIONS_NATIVE_PLATFORMS=slack` set temporarily: native Slack messages from a Hermes Agent and an OpenClaw Agent were mirrored as Conversation Messages, so they count as Requests, but they created 0 Communication Deliveries. They are therefore outside the handled rate and the response time.
- Not verified: the deployed value of the GitHub variable `COMMUNICATIONS_NATIVE_PLATFORMS`, which could not be read here. `operations.md` says `slack,discord`; the removed doc line said Slack, Discord, Telegram, and Teams.

Coverage:
- `kpis.spec.ts`: the headline test expects the new hint, the footnote test expects the new note, and a new test asserts that the page never says "Web Chat and Email". All three failed first on the old text.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 72 tests.

Follow-up, timing native channels (not in AF-348):
- Findings from the same local run, for the ticket:
  - **Pairing works.** A request and its reply share `session_key`, which includes the Slack thread on both runtimes. OpenClaw leaves `thread_id` empty on outbound rows, so pairing must use `session_key`.
  - **Hook times can understate the wait.** `occurred_at` is when a hook fired. A message sent while the OpenClaw Agent was restarting was answered 376 s later by Slack's own timestamps, but 15.8 s apart by recorded times.
  - **Timestamps differ by runtime.** OpenClaw stores the Slack timestamp of both the request and the reply, as message ids. Hermes stores it only for the request; its reply id is `outbound:<hash>`.
- Not verified: overlapping requests in one thread, multi-reply runs, approval prompts, verbose progress messages, and what a failed run leaves behind, which decides whether a native "handled" rate is measurable at all.

### 2026-10-02 — AF-348 — Live end-to-end check (local k3d)

Setup:
- You redeployed local k3d from this branch: a fresh database at migration `45bcefcb0749`, and the UI and API images built from `AF-348-organization-kpi-board`.
- The deployed UI bundle contains the `kpis` route and the UPPER_SNAKE exemption (`/^[A-Z0-9_]+$/`).
- As `admin@local.dev`, a new Organization "AF-348 KPI live check" was created through the API, with its creator as Owner.
- The KPIs page was driven in Chromium through the real login form at `https://agentfarm.local`.

Empty Organization:
- The nav reads Home, Costs, KPIs, Settings.
- The window reads "last 30 days".
- Value and Value per dollar read "— Set an hourly rate", with no `$0`.
- Handled reads "not enough data · based on 0 of 0 requests".
- The empty-state card shows, and both reads return 200.

With traffic:
- One Hermes Agent, "Tommy" (`general-purpose`), was hired and started.
- Two Web Chat messages went through the real API. The second asked Tommy to run `aai-cli excel workbook create /tmp/af348-kpi-check.xlsx`, a local file in the Agent's pod.
- Ingest recorded one Business Action: `excel workbook create`, `DOCUMENT_AUTHORED`, `SUCCESS`.
- One cost-sync run was started by hand (`kubectl create job --from=cronjob/agentbarn-api-cost-sync af348-cost-sync-manual-1`). It attributed 12 rows, $0.0557970824, to the Organization.

Every figure matched in independent SQL, the API, and the rendered page:

| Figure | SQL | API | Page |
|---|---|---|---|
| Requests | 2 inbound messages + 0 webhooks | 2 | 2 |
| Handled without failure | 2 SUCCEEDED, 0 failed | 1.0, coverage 2 | 100%, "based on 2 of 2 requests" |
| Median response | `percentile_cont` 6.469045 s over 2 first attempts | 6.4690445 | "6.5 s · 2 reqs" |
| LLM spend | $0.0557970824 | 0.0557970824 | $0.06 |
| Cost per Request | $0.0557970824 ÷ 2 | 0.0278985412 | $0.03 |
| Tool Calls per Request | 7 ÷ 2 | 3.5 | 3.5 |
| Hours saved (default 20 min) | 1 successful `DOCUMENT_AUTHORED` | 20 minutes | "0.3 h", "1 successful write" |
| Value (no rate) | — | null | "— Set an hourly rate" |

Saving through the Sheet:
- The rate was set to 60 and "Document authored" to 30 minutes.
- The browser sent `{"hourly_rate_usd":60,"outcome_minutes":{"DOCUMENT_AUTHORED":30}}`, and the real API answered 200. The Outcome Type key arrived unmangled.
- The Sheet closed. `/value-settings` and `/value` were read again, and `/value/activity` was not.
- The earlier write was recalculated:
  - Hours saved reads "0.5 h".
  - Value reads "$30.00 at $60.00/h".
  - Value per dollar reads "$537.66 per $1" (30 ÷ 0.0557970824 = 537.66).
  - The Agents table and Top outcomes match.
- Stored: `organization_value_settings.hourly_rate_usd = 60.00`, and `organization_outcome_minutes` `DOCUMENT_AUTHORED = 30`.
- Exactly one `security_audit_record` row, `organization.value_settings.changed`, with `field_changes` `hourly_rate_usd: null → "60.00"` and `outcome_minutes.DOCUMENT_AUTHORED: null → "30"`.

Final checks: `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 71 tests.

Not verified live:
- The Unattributed row, because the cost sync does not write such rows.
- A Member's view, because there is no second local account and no real email is sent. Both are covered by `kpis.spec.ts`.
- local k3d leaves `COMMUNICATIONS_NATIVE_PLATFORMS` empty, so the handled coverage here is not limited to Web Chat and Email the way it is in deployed environments.

### 2026-10-02 — AF-348 — Saving value settings, and UPPER_SNAKE request keys

Delivered:
- `use-update-value-settings.ts` sends `PUT …/value-settings` through `@/shared/api`.
  - On success it invalidates the Organization value family (`organizationValueKey.listScope({ organizationId })`) and the value settings detail. It never touches the activity family.
  - On error it raises a `toastError`.
- The Sheet's Save sends only the changed fields (`changesFrom`), closes on success, and stays open with the edits on failure.
- `ui/src/shared/api/interceptor/default.ts` leaves UPPER_SNAKE request keys (`/^[A-Z0-9_]+$/`) unchanged, beside the existing `-` exemption.

Defect found and fixed:
- `humps.decamelizeKeys` split every capital letter, so `{ outcomeMinutes: { MESSAGE_SENT: 7 } }` was sent as `{ outcome_minutes: { m_e_s_s_a_g_e__s_e_n_t: 7 } }`.
- The API rejects that key with 422, because `ValueSettingsUpdate` keys must be catalogue Outcome Types.
- No request body sent ALL-CAPS keys before this, and no response carries them, so nothing else changes.
- Docs: `docs/architecture/ui.md` (the transform invariant) and `docs/guidelines/webapp.md` (Schemas and API boundaries).

Coverage, `ui/tests/e2e/kpis.spec.ts`, with `interceptUpdateValueSettings` recording each `PUT` body:
- an override save sends exactly `{"outcome_minutes":{"MESSAGE_SENT":7}}`, closes the Sheet, and the tiles show the recalculated figures;
- a reset sends `{"outcome_minutes":{"MESSAGE_SENT":null}}`;
- a rate is sent as `75.5`, and an emptied rate as `null`;
- a failed save shows the server's message, keeps the Sheet open, and keeps the edit;
- a save refetches `/value` and never `/value/activity`.

Test-first:
- All 5 failed first, because no request was sent.
- With the save wired and the interceptor unchanged, the two override tests failed on the mangled key (`"m_e_s_s_a_g_e__s_e_n_t": 7`, and `: null`). The UPPER_SNAKE exemption turned them green.
- The activity guard was shown to fail (`Expected: 1, Received: 2`) with an activity invalidation temporarily added, which was then removed.
- `make lint-ui` and `make check-ui` pass.
- `kpis.spec.ts`, `top-nav-responsive.spec.ts`, `costs.spec.ts`, and the request-body specs `settings-agent-defaults.spec.ts`, `organization-llm-budget.spec.ts`, and `agent-configuration-page.spec.ts` pass, 114 tests.

### 2026-10-02 — AF-348 — KPIs value settings Sheet (read, edit, discard)

Delivered:
- `schemas.ts`: the value settings schema. `constants.ts`: `MAX_HOURLY_RATE_USD` and `MAX_OUTCOME_MINUTES`, mirroring `api/domains/business_value/models.py`.
- `use-value-settings.ts` reads through `@/shared/api`, keyed by `createQueryKeyStructure("value-settings").detail(organizationId)`.
- `value-settings-sheet.tsx` gives the panel described in the feature doc's [Value settings panel](../business-value.md#value-settings-panel).
  - The dirty-close flow follows `templates/components/template-editor.tsx` (`requestClose`, then confirm).
  - The draft is set from the stored settings when the form mounts, with no `useEffect`.
- Save validates but sends nothing yet. Saving is the next slice.

Coverage, `ui/tests/e2e/kpis.spec.ts`, with `valueSettings()` and `interceptValueSettings` in `kpis-data-support.po.ts` (catalogue order from `catalogue.py:31-41`):
- the rate and every row's minutes, with Default and Custom badges, the recalculation copy, and Save disabled while unchanged;
- a three-decimal rate and zero minutes rejected inline, with Save disabled;
- resetting an override;
- closing with edits by the close button and by Escape: Cancel keeps the edits, Discard closes, and reopening shows the stored values;
- closing without edits does not ask;
- a failed read with Retry.

Test-first:
- All 6 tests failed first: no "Value settings" button existed.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 66 tests.

### 2026-10-02 — AF-348 — KPIs empty state and loading skeletons

Delivered:
- `kpis-page.tsx`: the empty-state card replaces the chart and table when both responses list no Agents.
- Local skeletons in the tiles (`kpi-tile-skeleton`), the chart (`kpi-chart-skeleton`), and the table (`kpi-table-skeleton`). The rules are in the feature doc's [Empty and loading states](../business-value.md#empty-and-loading-states).
- The table waits for both endpoints to answer. While one was still loading, the table had shown "—", the same mark as a failed endpoint.

Coverage, `ui/tests/e2e/kpis.spec.ts`:
- An empty period shows the explanation, with no chart or table, and the tiles still render.
- With both reads held, all six tile skeletons, the chart skeleton, and the table skeleton show. Once released, the figures replace them.
- The mocks gain `hold`, which holds a response until the test releases it, so the loading state is reached without timing.

Test-first:
- Both tests failed first: no empty state existed, and loading showed no skeletons.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 60 tests.

### 2026-10-02 — AF-348 — KPIs Agents table and footnotes

Delivered:
- `agent-kpi-table.tsx`: the sortable per-Agent table, built like `costs/components/agents-by-spend.tsx` (the same sort state, header buttons, and `aria-sort`), with `Badge` for deleted Agents.
- `kpi-footnotes.tsx`: Top outcomes, the unverified and unclassified counts, and the value note.
- `utils.ts`: `mergeAgentRows` and `outcomeTypeLabel`. `format.ts`: `formatResponseTime` and `formatCount`.
- The rules are in the feature doc's [Agents table](../business-value.md#agents-table) and [Footnotes](../business-value.md#footnotes).

Decisions made while building, from the API contract:
- "Unattributed" labels only a null `agent_id`. `agent_identity` (`service.py:106-114`) can return a null name for a hard-deleted Agent, which reads "Deleted agent".
- An Agent missing from one response reads zero for that response's counts. The doc's row rules define both lists, so its absence means nothing to report there, not an unknown.
- An empty Top outcomes list reads "No successful writes in this period."

Coverage, `ui/tests/e2e/kpis.spec.ts`:
- rows merged from both reads and ranked by hours saved;
- per-Agent value and activity figures, including coverage and minute-scale response times;
- an activity-only Agent with zero value and "not enough data" rates;
- the Unattributed row, and a hard-deleted Agent with its badge;
- sorting, reversing, and unknowns last;
- no rate set;
- each endpoint failing alone, with Retry recovering;
- Top outcomes, the counts, and the note.

Test-first:
- All 9 tests failed first, because no table or footnotes existed.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 58 tests.
- At 1440px the ten-column table fits without scrolling.

### 2026-10-02 — AF-348 — KPIs trend chart

Delivered:
- `ui/src/features/business-value/components/kpi-trend-chart.tsx` uses `@/components/ui/chart` (Recharts 3.10.1), with `Tabs` switching between "Value vs spend" and "Requests". The rules are in the feature doc's [Trend chart](../business-value.md#trend-chart).
- It reuses `formatBucket`, `formatBucketLong`, `evenlySpacedTicks` (platform stats), and `formatSpendCompact` and `EmptyChart` (Costs).

Coverage, `ui/tests/e2e/kpis.spec.ts`:
- The chart opens on "Value vs spend" with two series drawn; switching to "Requests" draws one, and the value chart is unmounted.
- With no rate set, spend alone is drawn, with the note.
- A failed `/value` keeps "Requests" working.
- A failed `/value/activity` keeps "Value vs spend" working, and Retry recovers the "Requests" tab.

Test-first:
- All 4 tests failed first, because no chart existed.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 49 tests.

### 2026-10-02 — AF-348 — KPIs data layer, date range, and headline tiles

Delivered, in `ui/src/features/business-value/`:
- `schemas.ts`: Zod schemas for the `/value` and `/value/activity` responses. `outcome_type` is a plain string, so a new catalogue Outcome Type cannot fail parsing.
- `use-organization-value.ts` and `use-organization-activity.ts`, through `@/shared/api`.
  - Keys are `createQueryKeyStructure("organization-value")` and `("organization-activity")`, with the Organization ID in the list scope, so `ORG_SCOPED_QUERY_KEYS` is unchanged.
  - Both are disabled until an Organization is selected.
- The page header with one `DateRangePicker`. `from`/`to` live in the URL through `useCostUrlFilters`, and the echoed window is shown.
- Six tiles in one row at desktop width. The rules are in the feature doc's [Headline tiles](../business-value.md#headline-tiles).
- `StatCard` gains an optional `children` slot for the spend link and the Retry button. Costs does not pass it, and `costs.spec.ts` still passes unchanged.

Found and fixed during this slice:
- At desktop width each tile is 177px wide, and the value line truncated "Set an hourly rate" to "Set an hourly…".
- A test that checks the reason text is not cut off failed first (`"Set an hourly rate" is cut off in kpi-value`).
- A missing figure now shows "—" with its reason on the wrapping line below.

Coverage, `ui/tests/e2e/kpis.spec.ts`, with mocks in `ui/tests/pages/data-support/kpis-data-support.po.ts` (registered as `data.kpis`):
- populated tiles with the coverage hint;
- no rate: "Set an hourly rate" and no `$0`;
- zero spend: "not enough data";
- an unknown handled rate: not `0%`;
- rounding edges: "<0.1 h" and 99.6%;
- the default window: no params sent, and the echoed label;
- a chosen range: in the URL and on both reads;
- the spend link with and without a range;
- each endpoint failing alone, with the other's tiles intact and Retry recovering;
- a Member sends no value or activity read.

Test-first:
- The 11 tile tests failed first, because the tiles did not exist.
- The Member-read test cannot fail while the gate holds. With the gate's early return removed, it failed by catching both reads, and the gate was then restored.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 45 tests.

### 2026-10-02 — AF-348 — KPIs navigation, route, and access gate

Delivered:
- `ui/src/app/dashboard/[orgId]/kpis/page.tsx` renders `KpisPage` (`ui/src/features/business-value/components/kpis-page.tsx`), which gates with `useRequireOrgManager` before mounting the dashboard. The dashboard is only a heading so far.
- `top-nav.tsx` lists "KPIs" right after Costs, inside the same `canManageMembers` spread, so the desktop row and the mobile drawer both hide it from Members.

Coverage: `ui/tests/e2e/kpis.spec.ts`, with locators in `ui/tests/pages/kpis-page.po.ts`:
- an Owner sees KPIs right after Costs, on desktop and in the drawer, and following it opens the page with the tab marked current;
- a Member sees no KPIs entry, on desktop or in the drawer;
- a Member who opens `/kpis` is redirected to the Organization home.

Test-first:
- The three Owner and redirect tests failed before the change: KPIs was missing from the nav, and `/kpis` did not redirect.
- The two Member-entry tests cannot fail while no entry exists. They were shown to fail (`Expected: 0, Received: 1`) with the entry temporarily moved outside the role check, which was then restored.
- `make lint-ui` and `make check-ui` pass. `kpis.spec.ts`, `top-nav-responsive.spec.ts`, and `costs.spec.ts` pass, 32 tests; the 27 existing tests passed before the change too.

### 2026-10-01 — AF-345 — Review fixes: serialized value-settings saves and a simpler bucket query

Finding 1: a race on the first save, and an audit diff read outside the write.
- **Problem:**
  - `ValueSettingsRepository.save_with_event` selected the settings row and created it if it was missing. Two concurrent first saves both inserted, and the second failed on `uq_organization_value_settings_organization_id`, returning a 500.
  - `update_settings` also read the current values in separate sessions before the write, so two overlapping saves could record the same `previous`.
- **Fix:** `save_with_event` now owns the whole diff, in one transaction:
  1. `INSERT … ON CONFLICT DO NOTHING` for the settings row;
  2. `SELECT … FOR UPDATE` on that row;
  3. read the overrides;
  4. compare only the addressed fields;
  5. write;
  6. stage the event only when something changed. This follows `AgentRepository`'s update-with-event pattern.
- A plain `FOR UPDATE` would not have been enough: an Organization's first save has no row to lock.
- **Proven before the fix** on Postgres 18 (READ COMMITTED), with two concurrent connections:
  - the old path waits, then fails with `UniqueViolation`;
  - the new path waits, then records the value the other save committed, including overrides that save added.
- **Trade-off:** the first save that addresses anything creates the settings row, even a minutes-only save. `hourly_rate_usd = NULL` still means unset, exactly like no row. A request that addresses nothing still writes nothing.

Finding 2: `successful_counts_by_bucket` built a `generate_series` spine that `_series` never iterated.
- `_series` loops over `CostRepository.spend_series` buckets and looks counts up by key, so the extra `(bucket, None, 0)` rows were never used.
- The query is now a plain `GROUP BY` on `date_trunc(unit, timezone('UTC', occurred_at))` and `outcome_type`, the same key the spend spine uses.

Coverage:
- `test_value_settings.py::test_a_concurrent_first_save_waits_and_records_what_it_replaced`:
  - holds an uncommitted settings row on one connection, then sends `PUT /value-settings` from a second thread;
  - waits until `pg_stat_activity` shows that thread blocked on a lock, then commits.
  - Before the fix it failed with `IntegrityError` on the unique constraint. After it, the save returns 200 and records `previous: "10.00"`.
- The repository tests now assert the diff the repository computes:
  - an unchanged save stages no event and returns no delivery ids;
  - an unaddressed rate is left alone;
  - a minutes-only save leaves the rate unset;
  - a rejected event writes nothing.
- The 27 API tests are unchanged and pass.
- `test_organization_value.py::test_successful_counts_by_bucket_are_keyed_on_the_spend_series_buckets` now rejects gap rows. It failed against the spine, which returned 4 rows including `(…, None, 0)`, and passes with the `GROUP BY`. All 24 value tests pass, including the series tests that need every bucket.

### 2026-10-01 — AF-344 — Review fixes: backfill removes stale actions and writes only changes

Changed:
- `BusinessActionRepository.upsert_classified` is now `apply_classified`. Per batch and in one transaction it now:
  - deletes the rows of each classified Tool Call whose ordinal the new classification no longer produces, including every row of a Tool Call that now classifies to nothing
  - upserts with `ON CONFLICT … DO UPDATE … WHERE` any mapped column `IS DISTINCT FROM` the new value
- Before this, a path the catalogue later ignored kept its old rows (`is_write=true`, with an Outcome Type), so they would still have been valued, and the only safeguard was a manual-cleanup note. Every re-run also rewrote every row's `updated_at`.
- Ordinals count ignored invocations too, so the delete removes exactly the stale rows. A Tool Call whose classification raises is not passed to the repository and keeps its rows.
- `BackfillResult` and the summary line gain `removed`. `recorded` now counts rows inserted or actually changed, so a re-run with no catalogue change reports `recorded=0 removed=0`.
- `updated_at` moves only on rows whose mapping changed. The 2026-09-28 entry's "only `updated_at` moved" describes the behaviour before this fix.
- Updated docs: `operations.md` (the manual-cleanup note is gone), `business-value.md`, the RBAC brief's unscoped-method list, and the Makefile comment.

Coverage:
- `api/tests/integration/test_business_action_backfill.py` adds four tests:
  - removing the now-ignored action of an `&&` chain while keeping the other unchanged
  - removing every action of a Tool Call that now classifies to nothing
  - keeping rows when classification fails
  - a no-change re-run writing nothing (`updated_at` unchanged)
- The re-map test now checks `recorded=1` and that `updated_at` moved on the re-mapped row.

### 2026-09-30 — AF-346 — Organization activity API

Delivered: `GET /organizations/{organization_id}/value/activity` on `business_value_router`, with `Depends(get_stats_window)`. The feature doc's [Organization activity](../business-value.md#organization-activity) section is the contract.
- **Authorization:** `BusinessValueService.get_organization_activity` authorizes through the existing `_require_read` (`cost.read`, then `activity.read`).
- **Totals and per-Agent rows:** it builds both from `ValueActivityRepository` and `CostRepository`, with `activity_figures`.
- **Series:** it builds the series from `ConversationRepository.daily_direction_counts_since(..., organization_id=scope.organization_id)` plus the webhook bucket counts, merged by `utc_bucket`. No parallel message query was written.
- **Row identity:** `agent_identity` now gives both the value and the activity rows their name and deleted flag. The `/value` behaviour is unchanged.
- **Docstring:** `daily_direction_counts_since`'s docstring now names this caller. It had said the helper was reached only through `require_platform_admin` and that `agent_scope_predicates` was unusable.

Ticket corrections:
- The ticket names a shared `value_router`. The router is `business_value_router`, so the route lives there.
- Only OUTBOUND deliveries can be retried by hand. An INBOUND delivery's automatic retries keep the same row, which counts once at its final status. This is recorded under "Activity aggregates".
- An answer to a command approval arrives as a new inbound message and delivery (`web_chat/service.py`), so it counts as a Request. The feature doc lists it as a caveat.

Docs:
- `business-value.md` gains the Organization activity section, its reads in Boundaries, and change-impact rules.
- `CONTEXT.md` defines **Request**.
- `activity-and-ingest.md` Boundaries names this reader.
- `agent-webhooks.md` Change impact notes that every invocation is a Request.
- `INDEX.md` routes Organization activity to `business-value.md`.

Coverage:
- `api/tests/integration/test_organization_activity.py` gains 20 API tests:
  - Requests across messages and webhooks, with the series summing to the total
  - OUTBOUND ignored
  - the handled rate with UNAVAILABLE as a failure, and CANCELLED, PENDING, and PROCESSING left out
  - an automatically retried delivery: handled, but left out of the median
  - the interpolated median, and null figures without deliveries
  - null per-Request figures without Requests, and `0.0` cost with no spend
  - a native-only Agent with zero coverage
  - a soft-deleted Agent
  - a retired connection
  - an approval answer sent through the real Web Chat route
  - the half-open window and its echo, and 422 for an inverted window
  - the series buckets equal to `spend_series`
  - row union and order, including the Unattributed row
  - Admin 200, Member 403, non-member 403, and unauthenticated 401
- `api/tests/integration/test_cross_org_isolation.py`:
  - an Owner of Org A gets 403 on Org B's activity;
  - Org B's messages, webhooks, deliveries, tool calls, and spend never reach Org A's figures.
- All 22 failed first, on 404 before the route existed.
- `test_organization_value.py` and the unit tests still pass: 120 tests across the four files.

Live check (local k3d, deployed by the user at migration `45bcefcb0749`), with one Hermes Agent, "Tommy", in a fresh Organization:
- **Traffic:**
  - Three Web Chat messages went through the real API, one of them asking Tommy to run `date -u`.
  - The Agent was stopped through the API, and one more message returned `delivery_status: UNAVAILABLE`.
  - Webhooks cannot be created locally, because they require an enabled native Slack, Discord, Telegram, or Teams Connection and local k3d has none. One `webhook_invocation` row labelled "AF-346 e2e synthetic" (status `DISPATCH_FAILED`) was inserted instead, as the integration tests do.
- **Result:** `GET …/value/activity` matched SQL computed independently over the same window on every figure:

  | Figure | Endpoint | SQL |
  |---|---|---|
  | Requests | 5 | 4 inbound messages + 1 invocation |
  | Handled without failure | 0.75, coverage 4 | 3 SUCCEEDED, 1 UNAVAILABLE |
  | Median response | 1.462131 s, coverage 3 | `percentile_cont` over 1.255851, 1.462131, and 2.822847 s |
  | Cost per Request | 0.00700796592 | $0.0350398296 ÷ 5 |
  | Tool Calls per Request | 1.0 | 5 ÷ 5 |

  - The series put all 5 Requests in the 09:00 UTC bucket.
  - 981 older `cost_record` rows with no Organization were correctly left out.
- **Observed:**
  - 4 of the 5 Tool Calls (`read_file` ×3, `cronjob`) ran during the Agent's startup, before the first message. This confirms that Tool Calls per Request includes background work.
  - Spend lags live usage until the next cost sync: the newest attributed cost row was the first reply's.
- **Authorization on the live stack:** a Platform Administrator without a Membership got 403, a request with no token got 401, and an inverted window got 422.

Not verified live:
- Webhook ingress end to end, because it needs a native Connection. That path is covered by `test_agent_webhooks.py`.
- A Member's 403: there is no second account locally. That path is covered by the integration test.

### 2026-09-30 — AF-346 — Activity rules and DTOs

Delivered: pure module-level functions in `api/domains/business_value/service.py`, with nothing calling them yet:
- `per_request(amount, requests)`: `float(Decimal(amount) / requests)`, used for cost per request (on `Decimal` spend) and tool calls per request (on an integer count).
  - It is `None` when there are no requests.
  - Zero spend over some requests is `0.0`, not `None`.
- `handled_rate(succeeded, failed)`: successes over every handled outcome, `None` when there were none.
- `utc_bucket(bucket)`: a naive bucket is read as UTC, and an aware one is converted to UTC.
  - `CostRepository.spend_series` and `ValueActivityRepository.webhook_invocations_by_bucket` return naive buckets.
  - `ConversationRepository.daily_direction_counts_since` returns aware ones (`timezone('UTC', bucket)`).
  - This gives both forms of one instant the same merge key.

The response DTOs in `api/domains/business_value/models.py`:
- `ActivityTotalsRead`:
  - `requests`
  - `handled_without_failure_rate` and `handled_coverage`
  - `median_response_seconds` and `response_time_coverage`
  - `cost_per_request` and `tool_calls_per_request`
- `ActivitySeriesPoint`: `bucket` and `requests`.
- `AgentActivityRead`: the totals fields, plus `agent_id`, `agent_name`, `agent_deleted`, and `spend`.
- `OrganizationActivityRead`: the echoed window, plus `totals`, `requests_series`, and `agents`.

Coverage:
- `api/tests/unit/test_business_value_valuation.py` gains 10 tests:
  - division for spend and for counts, zero spend, and no requests
  - the handled rate, including its zero and null cases
  - a naive bucket, an aware non-UTC bucket, and naive and aware forms of one instant sharing a dictionary key
- All 10 failed first on `NotImplementedError` stubs, while the existing 22 still passed. All 32 pass.

### 2026-09-30 — AF-346 — Activity indexes

Delivered:
- Migration `45bcefcb0749` (revises `1045836844da`) adds two indexes, each declared in its model's `__table_args__`:
  - `ix_communication_delivery_agent_direction_completed` on `communication_delivery (agent_id, direction, completed_at)`, the shape the ticket names;
  - `ix_agent_chat_message_agent_direction_occurred` on `agent_chat_message (agent_id, direction, occurred_at)`.
- Both are built without CONCURRENTLY, like every other migration here.

Why the message index, which the ticket did not ask for:
- The "Activity aggregates" measurement spread its rows over 180 days, so a 30-day window was about a sixth of the table. The existing time index `ix_agent_chat_message_occurred_at_direction` could have been skipped for that reason alone.
- Re-run over 365 days, the read still seq-scanned (629 ms). That index holds every Organization's rows in the window, and the planner preferred a scan to reading that range and filtering down to one Organization's Agents.
- The index was added on that result, as agreed before the re-run.

Measured on local k3d (PostgreSQL 18.4), in one transaction ending in `ROLLBACK`:
- Data: the same synthetic data as "Activity aggregates", spread over 365 days, reading one of 20 Organizations over a 30-day window. The indexes were created exactly as the migration defines them.

  | Read | Before | With the index |
  |---|---|---|
  | deliveries | 1,468 ms (parallel seq scan) | 26.2 ms (bitmap scan on the new index) |
  | inbound messages per Agent | 629 ms (parallel seq scan) | 15.4 ms (bitmap scan on the new index) |
  | webhook invocations | 122 ms | 84 ms (unchanged index; no new index warranted) |
  | tool calls | 9.3 ms | 7.9 ms (unchanged index) |

Coverage:
- `test_activity_indexes_exist_after_migration` in `test_organization_activity.py` inspects the migrated schema. It failed first, listing the table's existing indexes, and passes after the migration.
- On a fresh Postgres 18 container, upgrading to head, downgrading to `1045836844da`, and upgrading again succeeds, and the indexes appear, disappear, and reappear.
- `compare_metadata` shows no index drift on either table. The only differences reported on them already existed: TEXT columns reported against `AutoString`, and the `agent_chat_message.conversation_type` enum variants noted in "Value settings tables".
- `make check-migrations` reports a single head, `45bcefcb0749`.

Not verified: production data distribution, hardware, and how long the index builds lock writes on real table sizes.

### 2026-09-30 — AF-346 — Activity aggregates

Delivered: `ValueActivityRepository` in `api/domains/business_value/repository.py`. Every read takes a `StatsWindow` and an `AuthorizationScope`, and filters on:
- the half-open window `[start, end)`;
- a join to `agent` with `agent_scope_predicates(scope, include_deleted=True)`, so a soft-deleted Agent's history still counts;
- the table's own `organization_id`, wherever the table has one.

The reads:
- `inbound_messages_by_agent`: INBOUND `agent_chat_message` rows by `occurred_at`. The table has no `organization_id`, so scoping is through the Agent join alone.
- `webhook_invocations_by_agent` and `webhook_invocations_by_bucket`: `webhook_invocation` rows of every status, by `created_at`. The bucket read uses the same UTC `generate_series(date_trunc(...))` spine as `CostRepository.spend_series`.
- `delivery_outcomes_total` and `delivery_outcomes_by_agent`: INBOUND `communication_delivery` rows by `completed_at`, limited to SUCCEEDED, DEAD_LETTERED, and UNAVAILABLE. They return the three counts, the first-attempt success count, and `percentile_cont(0.5)` over `completed_at − created_at`, filtered to SUCCEEDED with `attempt_count = 1` and cast to `double precision`. The median is null when nothing qualifies.
- `tool_calls_by_agent`: `tool_call` rows of every status, by `occurred_at`.

Ticket correction:
- The ticket says a dead-lettered delivery that is retried and later succeeds counts as succeeded.
- Only OUTBOUND deliveries can be retried by hand (`delivery_repository.py` `retry_dead_lettered`). An INBOUND retryable failure, including a lease-expiry reclaim, returns the same row to PENDING and keeps `attempt_count`, which only a claim increments. It ends SUCCEEDED with `attempt_count ≥ 2`, and DEAD_LETTERED is terminal for INBOUND.
- The tests therefore cover an automatically retried delivery: it counts as succeeded and is left out of the median.

Test support: `api/tests/steps/communication.py`.
- It seeds connections, inbound deliveries through `CommunicationDeliveryRepository.accept_inbound` (with the status, attempt count, and timestamps overridden afterwards), outbound deliveries, messages, webhook invocations, and tool calls. It also soft-deletes the current Agent the product way.
- `accept_inbound` refuses a deleted Agent, so the soft-deleted case seeds its rows first and deletes afterwards.

Coverage: `api/tests/integration/test_organization_activity.py`, 10 repository tests:
- per-Agent inbound messages, including the half-open window and ignoring OUTBOUND and other Organizations;
- a soft-deleted Agent's messages;
- webhook invocations of every status, including the window and other Organizations;
- the webhook bucket spine, which equals `spend_series`'s buckets;
- the delivery statuses: CANCELLED, PENDING, PROCESSING, and OUTBOUND are left out, and UNAVAILABLE comes from a stopped Agent;
- the `completed_at` window;
- the median over first-attempt successes only (10 s and 20 s give 15.0, with a retried 600 s success excluded), and a null median with no deliveries;
- the per-Agent split, including a soft-deleted Agent and another Organization;
- tool calls of every status, including the window and other Organizations.

All 10 failed first on `NotImplementedError` stubs, with every seeding step completing. `test_organization_value.py` and `test_business_action_repository.py` still pass, and `api.api_app` and `api.ingest_app` import cleanly.

Index check (local k3d, PostgreSQL 18.4):
- Setup: one transaction ending in `ROLLBACK`, so nothing persisted.
  - Rows: 20 synthetic Organizations and 200 Agents (marked deleted to skip template pinning; the reads do not filter on `deleted_at`), 500,006 `agent_chat_message`, 1,000,006 `communication_delivery` (half OUTBOUND), 100,000 `webhook_invocation`, and 500,024 `tool_call` rows.
  - All rows were spread evenly over 180 days, and the tables were analyzed.
  - Each query was compiled from the repository code and run with `EXPLAIN (ANALYZE, BUFFERS)` for one Organization over a 30-day window.
- Without new indexes:

  | Read | Plan | Time |
  |---|---|---|
  | deliveries | parallel sequential scan | 1,405 ms |
  | inbound messages per Agent | parallel sequential scan; `ix_agent_chat_message_occurred_at_direction` not chosen | 606 ms |
  | webhook invocations | bitmap scan on `ix_webhook_invocation_webhook_created` | 91 ms |
  | tool calls | `ix_tool_call_agent_occurred` | 10 ms |

- Candidate indexes, each created inside the same rolled-back transaction:

  | Index | Read | Time |
  |---|---|---|
  | `communication_delivery (agent_id, direction, completed_at)`, the ticket's shape | deliveries | 17.6 ms |
  | `communication_delivery (organization_id, direction, completed_at)` | deliveries | 12.4 ms |
  | `communication_delivery (completed_at, organization_id)` | deliveries | 16.5 ms |
  | `agent_chat_message (agent_id, direction, occurred_at)` | inbound messages per Agent | 45 ms (index-only scan) |

- The planner serves the ticket's Agent-first shape with a nested loop over the Organization's Agents and a range scan per Agent. A planning review had claimed that shape could not serve an Organization-wide range; this measurement shows it can.
- Not verified: production data distribution and hardware. This was a laptop with evenly spread synthetic rows.

### 2026-09-29 — AF-345 — gog (Google Workspace) classification

Scope: added to AF-345 at the user's request, and noted on the PR.

Why:
- Google Workspace Integrations reach Google only through gog (`integrations.md`). The classifier matched only `aai-cli`, so all of an Agent's Gmail, Calendar, Drive, and Sheets work produced no Business Action.
- aai-cli's own `drive` group has no credential in Agent Barn, so it did not cover this work either.

Evidence (local k3d, gog `v0.37.0 (45b5d766)`, identical binary sha256 `ba1a5b40…36e0c` in both runtime images):
- `gog schema --json` has 586 leaf commands, and 209 of them belong to the four services a Google Workspace credential can grant. No node marks commands as reads or writes.
- Errors are plain text on stderr, with no JSON envelope even with `--json`. A missing account and a usage error both exit `2`.
- Empty results exit `0`. Exit `3` happens only with the opt-in `--fail-empty`.
- `--dry-run` exits `0` and prints `{"dry_run": true, …}`. A search afterwards confirmed nothing was created.
- Live Web Chat Tool Calls:
  - Hermes, a failed read: `exit_code` 2.
  - Hermes, a successful read: `exit_code` 0.
  - Hermes, a successful write: `drive mkdir`, `exit_code` 0. The user ran it against their own workspace; it left one empty folder, `agentbarn-gog-probe`.
  - OpenClaw: the Agent appended `; echo "EXIT_CODE:$?"`, which hid gog's exit code.
  - None of them produced a Business Action before this change.

Delivered:
- `api/domains/business_value/gog_catalogue.py`:
  - all 209 command paths, classified by hand under the same rules as aai-cli: 84 reads, 16 ignored, and 109 writes over the existing 10 Outcome Types;
  - alias tables, top-level shortcuts, value-taking global flags, and ignored tooling commands, generated from the recorded command tree.
- The classifier recognises `gog` alongside `aai-cli`:
  - `integration` is `google-<service>`, keeping it apart from aai-cli's `drive` and `email` groups.
  - Dry runs, help, tooling, and ignored entries are dropped.
  - Other Google services are stored as unclassified.
  - gog ordinals follow the aai-cli ordinals, so no stored ordinal moves.
  - Status comes from the exit code only. Exit `3` counts as success only for a single gog command.
- The `agentbarn_business_actions` metric labels the four `google-*` integrations by name; any other value is still `other`.
- The runtime config digest is unchanged: `4827db07…f9d47` before and after, for fixed image names. No `business_value` module is in the Agent start closure.

Coverage:
- Fixtures:
  - `api/tests/fixtures/business_actions/gog_hermes.json` (3) and `gog_openclaw.json` (1) hold the real Tool Calls. Every string inside gog's JSON output is redacted.
  - `api/tests/fixtures/gog/command-tree.json` is the pruned command tree: names, aliases, one-line help, and global flags. It contains no account data.
- `api/tests/unit/test_gog_catalogue.py` (19) checks the catalogue against that tree in both directions: paths, aliases, shortcuts, and value flags.
  - It checks that both Dockerfiles still pin the recorded version, so a gog upgrade fails CI until the tree is re-recorded.
  - It checks the Outcome Type rules.
- `test_business_action_classifier.py` gains 37 gog tests:
  - command paths and aliases, including flags in any position
  - ignored invocations, ordinals in mixed commands, and exit-code statuses
  - the four fixtures
- `test_metrics.py`: the label for a granted gog service versus an ungranted one.
- `test_ingest.py` posts the gog fixtures through the Ingest endpoint.
- `test_business_action_backfill.py`:
  - classifies stored gog history;
  - adds gog actions after an aai-cli action that was stored before gog support, without renumbering it.
- `test_organization_value.py`: a gog write recorded through the repository is valued in `GET /value`, and a failed one is reported as failed.
- Test-first:
  - Every new classifier, catalogue, and metric test failed first.
  - The Ingest, backfill, and valuation tests were added once the classifier existed; the same fixtures had failed at the classifier.
- Running the new classifier over the four unredacted gog Tool Calls stored on local k3d gave exactly the fixtures' expected actions.

Not verified:
- The exit code when Google refuses a write under a read-only credential. It would need a read-only credential and a write attempt.

Live check after deploying to local k3d (2026-09-29, migration head `1045836844da`, fresh database):
- **Ingest recorded each gog Tool Call:**
  - Hermes `gog calendar calendars` (exit 0): `google-calendar`, read, SUCCESS.
  - OpenClaw `gog gmail labels list` (exit 2, no credential): `google-gmail`, read, ERROR.
  - Hermes `gog drive mkdir` (exit 0), run by the user: `google-drive`, `RECORD_CREATED`, SUCCESS.
- **Metric:** the Ingest `/metrics` exported the `google-calendar` and `google-gmail` labels by name.
- **Backfill:** two backfill runs left the rows identical in id, mapping, status, and `created_at`. These runs predate AF-344's review fix, under which a no-change re-run reports `recorded=0`.
- **Value report:** `GET /value` counted the reads as not valued, with the rate at $60.
- **Incident:** one read-back started a second full-app Python process inside the `api` container. That pushed it over its 512Mi limit, and it was OOMKilled and restarted. Later checks used `psql` in the Postgres pod instead.

### 2026-09-29 — AF-345 — Organization value API

Delivered: `GET /organizations/{organization_id}/value` with `Depends(get_stats_window)`. The response echoes the resolved window and returns four parts.
- **`totals`:**
  - successful writes, minutes saved, value, spend, and the value-to-spend ratio
  - unverified, failed, and unclassified counts
  - the hourly rate used
- **`series`:** `bucket`, `minutes_saved`, `value`, and `spend` per UTC bucket, emitted with an explicit UTC offset.
- **`agents`:** a full outer merge of the Business Action counts with `CostRepository.spend_by_agent`.
  - Names come from `AgentRepository.find_all_for_org`, which includes deleted Agents. A hard-deleted Agent falls back to the cost record's name.
  - A null id is labelled `"Unattributed"`.
  - Rows are ordered by minutes saved, then spend.
- **`top_outcome_types`:** ordered by minutes saved, then count.

Value is computed at read time in `Decimal` and emitted as a float. It is null, as is every ratio, until a rate is set. A ratio is also null when spend is zero.

Spend comes from `CostRepository` with an Organization-only `CostFilter`, with no Agent join. `costs.md` Boundaries now names Business Value as a reader.

Ticket correction:
- Cost sync attributes all-or-nothing (`costs/sync.py:295-296`), so spend with no Organization is never in any Organization's total.
- The org-scoped "Unattributed" row appears only for a cost row with an Organization but no Agent, which the sync does not write today.
- The row is kept, mirroring Costs, and tested with a synthetic row (`there_are_cost_records(without_agent=True)`).

Docs:
- `business-value.md` gains the Organization value section, the category table, source map entries, and change-impact rules.
- `CONTEXT.md`'s Outcome Type entry now defines unclassified (including Outcome Types no longer in the catalogue), unverified, and failed writes.

Coverage:
- `api/tests/integration/test_organization_value.py` adds 17 API tests:
  - totals and the echoed window, and the half-open period for both actions and spend
  - the per-Agent split, including a soft-deleted Agent, the Unattributed row, and a hard-deleted Agent
  - an Agent with work but no spend
  - top Outcome Types and their tie-break
  - the series with its full UTC bucket spine
  - overrides applied, a null rate, and zero spend
  - the unverified, failed, and unclassified counts
  - an empty period
  - Admin 200, Member 403, non-member 403, and unauthenticated 401
- `api/tests/integration/test_cross_org_isolation.py`:
  - an Owner of Org A gets 403 on Org B's `/value`
  - Org B's Business Actions and spend never appear in Org A's figures
- All 17 API tests failed first, on 404 before the route existed.
- `test_value_settings.py` (43) and the relevant subset of `test_costs.py` (11) still pass.

### 2026-09-29 — AF-345 — Value aggregates

Delivered: three read methods on `BusinessActionRepository`. They return raw counts grouped by Outcome Type; valuation happens in the service.

Every method filters on:
- `business_action.organization_id`, which uses the existing `(organization_id, occurred_at)` index
- the half-open window `[start, end)` on `occurred_at`
- a join to `agent` with `agent_scope_predicates(scope, include_deleted=True)`, so a soft-deleted Agent's work still counts

The methods:
- `category_counts(window, scope)` returns `(is_write, outcome_type, status, count)` for every action, so the service can categorise it.
- `successful_counts_by_bucket(window, scope)` returns `(bucket, outcome_type, count)` for SUCCESS writes that have an Outcome Type.
  - The rows are left-joined onto the same UTC `generate_series(date_trunc(...))` spine as `CostRepository.spend_series`, so empty buckets are present and the two series merge by key.
- `successful_counts_by_agent(window, scope)` returns `(agent_id, outcome_type, count)` for the same successful writes.

Test support:
- `api/tests/steps/business_action.py:there_are_business_actions(...)` inserts one Tool Call and its Business Actions directly for `context.agent`. It sets the Outcome Type, `is_write`, status, count, and `occurred_at`.

Coverage: `api/tests/integration/test_organization_value.py`, 6 repository tests:
- grouping by `(is_write, outcome_type, status)`
- the half-open window: the start is included and the end is excluded
- a soft-deleted Agent is included
- another Organization's actions are excluded from all three reads
- per-Agent counts include only successful classified writes
- the bucket spine equals `spend_series`'s buckets for the same window, empty buckets included, and each write lands in its UTC day

All 6 failed first against `NotImplementedError` stubs. `test_business_action_repository.py` and `test_business_action_backfill.py` still pass, and the app entrypoints import cleanly with the new `agents` import.

### 2026-09-29 — AF-345 — Value settings API

Delivered:
- `GET` and `PUT /organizations/{organization_id}/value-settings`, in `api/domains/business_value/routes.py`, registered in `api/api_app.py`.
- `BusinessValueService` authorizes through `PermissionPolicy.require_organization`:
  - reads require `cost.read`, then `activity.read`
  - writes require `organization.update`
- The service compares each field the request addresses with what is stored.
  - A rate is compared as a Decimal, so `42.5` and `"42.50"` count as the same.
  - An unchanged save writes nothing and emits no event.
  - Otherwise it saves through `save_with_event` and calls `EventDeliveryDispatcher.enqueue_immediate` after commit.
- `ValueSettingsUpdate` validation (confirmed with pydantic 2.13.4 before the build):
  - The rate is a `Decimal` from 0 to 10,000.00, with at most two decimal places.
  - Minutes are strict JSON integers from 1 to 1,440.
  - Keys must be catalogue Outcome Types. Anything else returns 422.
- Responses report the rate as a float, following the Costs convention.
- Docs: `business-value.md` gains a Value settings section (it replaces "There is no product read endpoint yet") plus its source map and change impact. `docs/INDEX.md` routes value settings and the value KPI here, and `domain-events.md` names the emitting route.

Test fixture finding:
- `there_is_an_organization_with_user_and_access_token(role=...)` always makes the user Owner (`api/tests/steps/organization.py:44-49`); its `role` never reaches the membership.
- The new tests add Admin and Member actors with `there_is_a_user(role=...)`, as `test_costs.py` does. The helper itself is unchanged.

Coverage:
- `api/tests/integration/test_value_settings.py`, 27 new tests:
  - Owner and Admin get 200; Member, non-member, and a Platform Administrator without a Membership get 403; an unauthenticated caller gets 401.
  - Defaults on a new Organization; setting a rate and an override.
  - Exactly one event with string `field_changes`; no event for an unchanged or empty save.
  - An omitted rate is kept; a null rate clears it; a null override reverts to the default.
  - A stored override outside the catalogue is ignored.
  - Twelve 422 cases, each storing nothing.
  - Projection to a durable `security_audit_record`.
- `api/tests/integration/test_cross_org_isolation.py`: an Owner of Org A gets 403 on `GET` and `PUT` for Org B.
- Every new test failed first, on 404s or missing response fields, before the routes existed.

### 2026-09-29 — AF-345 — Value settings persistence

Delivered: `ValueSettingsRepository` in `api/domains/business_value/repository.py`.
- `get_hourly_rate(organization_id)` returns `None` when no rate is set.
- `get_minute_overrides(organization_id)` returns the stored overrides keyed by Outcome Type. They are returned raw; the service ignores any Outcome Type outside the catalogue.
- `save_with_event(...)` copies the `AgentSettingsRepository.set_default_model_with_event` pattern. It opens one session and commits once, so a settings change is never visible without its audit record.
  - **Rate:** written only when `rate_changed` is set. The settings row is created lazily, so a save that changes only minutes creates none.
  - **Minutes:** a `None` minute change deletes the override. An integer upserts it on `(organization_id, outcome_type)`.
  - **Event:** built through `EVENT_REGISTRY` with an Organization subject, then staged through the outbox with its Event Deliveries. The delivery ids are returned for post-commit enqueue.
- The caller decides what changed and supplies `field_changes`, so the repository never decides whether an event is warranted.

Coverage: `api/tests/integration/test_value_settings.py` covers:
- a rate and an override that read back after saving
- exactly one staged event carrying the diff, with an Organization subject and its committed delivery ids
- an upsert of an existing override, deletion by `None`, a minutes-only save that creates no settings row, clearing the rate, and an Organization with nothing set
- atomicity: an event the registry rejects leaves no settings rows and no event
- All 8 new tests failed first, against `NotImplementedError` stubs.
- `test_business_action_repository.py` still passes, and `api.ingest_app` and `api.api_app` import cleanly with the new events import.

### 2026-09-29 — AF-345 — Valuation rules

Delivered: module-level functions in `api/domains/business_value/service.py`. They are pure; valuation happens when figures are read.
- `effective_minutes(overrides)` returns `DEFAULT_MINUTES` with an Organization's overrides applied. An override for an Outcome Type that is no longer in the catalogue is ignored.
- `value_usd(minutes, rate)` computes `Decimal(minutes) * rate / 60`, unrounded, so the value stays exact until it is emitted as a float. It is `None` when no rate is set.
- `value_to_spend_ratio(value, spend)` is `None` when there is no value or the spend is zero.
- `categorise(rows)` takes counts grouped by `(is_write, outcome_type, status)` and puts each action in exactly one category. An action is classified when it is a write whose Outcome Type is in the current catalogue.
  - Successful: a classified SUCCESS, counted per Outcome Type. This is the only valued category.
  - Unverified: a classified UNKNOWN.
  - Failed: a classified ERROR.
  - Unclassified, at any status: a path outside the catalogue, a write with no Outcome Type, or a write whose Outcome Type is no longer in the catalogue.
  - Reads are not counted in any category.

Coverage:
- `api/tests/unit/test_business_value_valuation.py` has 22 tests.
  - They cover overrides, stale override keys and stale action types, and every category.
  - They also cover summing counts across rows, empty input, a null rate, a zero rate, zero spend, and Decimal exactness.
  - Before the implementation they failed inside `NotImplementedError` stubs. They pass now.

### 2026-09-29 — AF-345 — Value settings audit event

Delivered:
- `organization.value_settings.changed`, schema v1, is registered in `build_default_event_registry` with Organization scope. It is routed to `security_audit.projection`, and `SecurityAuditProjection.supported_events` lists it.
- `OrganizationValueSettingsChangedPayload` uses `extra="forbid"` and carries:
  - `organization_id`
  - `field_changes: dict[str, dict[str, str | None]]`, keyed `hourly_rate_usd` or `outcome_minutes.<OUTCOME_TYPE>`, each holding `previous` and `current`
  - `actor_display` and `subject_display`
- Every value in `field_changes` is a string or `null`. The later settings service renders the rate to two places and minutes as integers.
- `docs/features/domain-events.md` lists the event.

Coverage:
- `api/tests/unit/test_event_handler_registry_wiring.py` includes the event. It failed with `supports(...) is False` before the projection registration and passes after.
- `api/tests/unit/test_domain_events.py` passes unchanged.

### 2026-09-29 — AF-345 — Value settings tables

Delivered:
- Migration `1045836844da` (revises `39ea6a8e2fe4`) adds two tables.
- `organization_value_settings`: one row per Organization.
  - `organization_id` is unique, with a foreign key using `ON DELETE CASCADE`.
  - `hourly_rate_usd` is a nullable `NUMERIC(12,2)`, checked to be `NULL` or `>= 0`.
- `organization_outcome_minutes`:
  - `organization_id` is a foreign key with `ON DELETE CASCADE`.
  - `outcome_type` is a `VARCHAR(64)`, matching `business_action.outcome_type`.
  - `minutes_saved` is an integer checked to be `> 0`.
  - `(organization_id, outcome_type)` is unique.
- The bounds the API will enforce are constants in `api/domains/business_value/models.py`: `MAX_HOURLY_RATE_USD = 10000.00` and `MAX_OUTCOME_MINUTES = 1440`.

Coverage:
- `api/tests/integration/test_value_settings.py` covers the migrated schema:
  - both tables exist, and a rate reads back as an exact two-place decimal
  - the rate and minutes check constraints, and both uniqueness constraints
  - deleting an Organization cascades both tables
- `test_rbac_schema.py::test_downgrade_to_rbac_revision_removes_general_access_column` downgrades through the new migration.
- Checked by hand, not in CI, on a fresh Postgres container:
  - upgrading to head, downgrading to `39ea6a8e2fe4`, and upgrading again succeeds
  - `compare_metadata` scoped to the two tables shows no drift
  - The only other difference reported is an existing mismatch in the `agent_chat_message.conversation_type` enum variants, unrelated to this change.

### 2026-09-28 — AF-344 — Live end-to-end check (local k3d)

Setup:
- The API image was deployed and migration `39ea6a8e2fe4` applied, on a fresh database.
- One Hermes and one OpenClaw Agent each ran six prompts through Web Chat, with no integrations connected.

Results:
- All 13 completed shell Tool Calls were classified as expected, producing 12 Business Actions:
  - `excel workbook create`: `DOCUMENT_AUTHORED`, SUCCESS
  - `jira issues get` with no profile: ERROR
  - an `&&` chain: two SUCCESS actions
  - `…; echo done`: UNKNOWN
  - `github prs create` with no profile: `PULL_REQUEST_OPENED`, ERROR
  - `ls -la` and Hermes's own `mkdir …` housekeeping: no rows
- There were no duplicate `(tool_call_id, ordinal)` rows and no shell Tool Calls left `PENDING`.
- `agentbarn_business_actions_total` on the Ingest `/metrics` (port 8001) summed to the same 12:
  - excel/true/success 6
  - jira/false/error 2
  - excel/false/unknown 2
  - github/true/error 2
- The backfill ran twice through `kubectl exec deploy/agentbarn-api -c api -- python -c "…backfill import main; main()"`. Both runs logged `scanned=13 recorded=12 failed=0`.
  - Rows were identical before and after in id, mapping, status, and `created_at`.
  - Only `updated_at` moved, because the upsert always sets it.
- Not exercised live: backfilling Tool Calls that pre-date the release, because the database was fresh. That path is covered by `test_business_action_backfill.py`.

### 2026-09-27 — AF-344 — Backfill

Delivered:
- `api/domains/business_value/backfill.py:main` walks completed `terminal`/`exec` Tool Calls in id-keyset batches (`BACKFILL_BATCH_SIZE = 500`). It classifies each one from its stored content, never from its stored status.
- It upserts on `(tool_call_id, ordinal)`, updating `integration`, `resource`, `verb`, `is_write`, and `outcome_type` and leaving `status` alone, so a re-run after a catalogue change re-maps history. It never deletes.
- It logs one summary line: `scanned`, `recorded`, `failed`.
- `make backfill-business-actions` uses the `python -c` form of the `reconcile-*` targets and is listed in `.PHONY`.
- `docs/guidelines/operations.md` documents the backfill with the `kubectl -n <namespace> exec deploy/<release> -c api -- python -c …` command.
  - Checked on the local k3d API pod: the container is named `api`, the working directory is `/app`, and `api.*` imports from `python`.

Decision:
- The RBAC brief's background-work exception now covers operator-run one-shot commands as well as schedules, and names the backfill's two unscoped repository methods. It previously required "a schedule". The other two conditions are unchanged: not reachable from a router, and request paths keep their `AgentAuthorization` checks.

Coverage:
- `api/tests/integration/test_business_action_backfill.py` covers:
  - classification across several batches, skipping non-shell and incomplete Tool Calls
  - a Hermes Tool Call stored as SUCCESS with exit 3 becoming ERROR
  - a re-run producing no duplicates
  - a re-map after a catalogue change leaving the stored status unchanged

### 2026-09-27 — AF-344 — Ingest recording and metric

Delivered:
- `IngestService._process_tool_calls` calls `BusinessActionRepository.record_in_session(session, tool_call)` right after `complete()` returns a row, inside the batch's single transaction.
- `agentbarn_business_actions` counter, next to `agentbarn_tool_calls` in `api/core/metrics.py`. It is scraped from the Ingest process's `/metrics` (port 8001).
  - Labels: `integration`, clamped to the bundled command groups and otherwise `other`; `is_write` (`true`/`false`/`unknown`); and `status`.
  - It counts only rows actually inserted, so retried batches do not double-count.
- The feature doc [`business-value.md`](../business-value.md) covers classification, status inference, the Outcome Type table and its sign-off, and every known undercount. It also states that this is not the Agent Activity tab.
- `activity-and-ingest.md` now says Ingest also writes Business Actions.

Coverage:
- `api/tests/integration/test_ingest.py` covers:
  - a successful write, a failed write (envelope), and a read
  - a non-aai-cli command and an `&&` chain producing two SUCCESS actions
  - a repeated batch producing no duplicates, and an orphaned result creating nothing
  - all 35 recorded Hermes and OpenClaw Tool Calls, posted through the Ingest endpoint
- `api/tests/unit/test_ingest_service.py` and `api/tests/unit/test_metrics.py` cover the wiring and the counter labels.

Local test note:
- On Windows with Docker Desktop, testcontainers reached Postgres over `localhost` (`::1`), and that connection started failing mid-session.
- `TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1` fixed it for the local run. No repository change was made.

### 2026-09-27 — AF-344 — Table and repository

Delivered:
- Migration `39ea6a8e2fe4` adds `business_action`, with these columns:
  - `organization_id`, `agent_id`, and `tool_call_id`, each a foreign key with `ON DELETE CASCADE`
  - `ordinal`, `integration`, `resource`, and `verb`
  - `outcome_type`, a nullable `VARCHAR(64)`
  - `is_write`, nullable, where `NULL` means the path is not in the catalogue
  - `status`, the `businessactionstatus` enum
  - `occurred_at` and `completed_at`
- It also adds a unique `(tool_call_id, ordinal)` constraint and indexes on `(organization_id, occurred_at)` and `(agent_id, occurred_at)`. There are no argument or result columns.
- `BusinessActionRepository.record_in_session(session, tool_call)` classifies the Tool Call and inserts inside a savepoint of the caller's session, with `ON CONFLICT (tool_call_id, ordinal) DO NOTHING`. It returns only the rows it inserted.
  - A database error rolls back only that savepoint.
  - A classification error is logged with the Tool Call id and skipped.
- ADR [`2026-09-25-classify-business-actions-at-ingest`](../../adr/2026-09-25-classify-business-actions-at-ingest.md) records why the rows live in PostgreSQL rather than PostHog or OpenPanel.
- `CONTEXT.md` defines Business Action and Outcome Type.

Coverage:
- `api/tests/integration/test_business_action_repository.py` covers:
  - persisted rows, tenancy, and timing
  - a non-aai-cli command
  - a duplicate result
  - a foreign-key violation leaving the Tool Call batch committed
  - a classifier failure
  - cascade on Tool Call deletion
- Checked by hand, not in CI: Alembic `compare_metadata` against a fresh database at head shows no drift for `business_action`, and downgrading to `73e85ce78653` then upgrading again succeeds.

### 2026-09-27 — AF-344 — Classifier

Delivered:
- `classify(tool_call)` turns a `terminal`/`exec` Tool Call into content-free Business Actions. It stores no arguments and no results.
- It finds each aai-cli invocation by executable basename, after any `VAR=value` assignments.
- It unwraps the `AGENTBARN_TOOL_SESSION=… AGENTBARN_TOOL_INVOCATION=… sh -c '…'` wrapper.
- It splits commands on `&&`, `||`, `|`, `;`, `&`, newlines, and subshell parentheses.
- It strips the four global flags in both forms, in any position.
- It ignores `--help`, `-h`, `help` subcommands, and invocations with no command path.

Status rules (the same for both runtimes):
- Exit evidence comes from Hermes `exit_code` or OpenClaw `details.exitCode` with `details.status: completed`.
- The aai-cli error envelope overrides a zero exit.
- SUCCESS needs a zero exit that covers the action: an `&&`-only chain, or the last segment.
- With several actions, a failure is attributed only when exactly one action matches the envelope's `service`. Every other action is UNKNOWN.
- Background runs and missing evidence are UNKNOWN.

Decisions:
- `--version` is not treated as a help flag. It is a real `confluence pages update` option (`[--version N]`), and aai-cli has no global `--version`. A bare `aai-cli --version` has no command path, so it is still ignored.
- The ordinal counts every aai-cli invocation in the command, ignored ones included. A later catalogue change that starts ignoring a path therefore does not shift the ordinals of stored rows.
- Invocations inside `$(…)`, `(…)`, or after `&` are recorded but never SUCCESS, because the command's exit code does not cover them.

Coverage:
- `api/tests/unit/test_business_action_classifier.py` covers:
  - command parsing, ignored invocations, and the wrapper in both quoting styles
  - chain operators, envelope attribution, and per-runtime evidence
  - all 35 recorded pre-flight Tool Calls

### 2026-09-27 — AF-344 — Command catalogue

Delivered:
- The catalogue marks every command path in the 12 bundled `command-reference.md` files as read, write, passthrough (`request`), or ignored.
  - It covers 411 reference lines. The only lines skipped are the three generic `<resource> <action>` placeholders in excel, drive, and email.
  - Every catalogue path appears in a reference.
- Each of the 90 write paths maps to one of 10 Outcome Types. Deletes always map to `RECORD_DELETED`, and edits to an existing comment map to `RECORD_UPDATED`.
- Housekeeping commands (`microsoft auth`, `hubspot health`, `hubspot events custom send`, `hubspot conversations visitor-identification tokens create`) are ignored. So are the aai-cli tooling groups `config`, `skills`, `secrets`, and `help`.
- The catalogue lives outside `aai_cli_skills/bundled/`, so it does not change the runtime digest.

Coverage:
- `api/tests/unit/test_business_action_catalogue.py` checks four things:
  - the catalogue's integration set equals the bundled command groups
  - every bundled path is covered
  - every write has an Outcome Type
  - every Outcome Type has default minutes

### 2026-09-27 — AF-344 — Pre-flight evidence

Delivered:
- Fixtures `api/tests/fixtures/business_actions/hermes.json` and `openclaw.json` hold 35 real `terminal`/`exec` Tool Calls from a local k3d cluster, sent through Web Chat with no platform and no integration connected.
- Each fixture keeps `tool_name`, `arguments`, the stored `result`, the stored Tool Call status, and the expected Business Actions. Agent ids, external ids, and timestamps were dropped; nothing else was sensitive.

Runtime versions:
- Hermes Agent `v0.20.5 (2026.8.19)` and OpenClaw `2026.8.2 (0965053)`, confirmed in the running pods.
- Images: `agentfarm-hermes-base@sha256:368bc70daf5d5f1592826b53752d546405a822945179efbf99df77558d8af12c` and `agentfarm-openclaw-base@sha256:f70a365067f3ce588eb82d55cdbca71ef83e5ac5e4a4a86b4495c0d97ca94c9d`.

aai-cli version:
- `aai-cli --version` does not exist and fails with `unexpected argument '--version'`, because the clap parser declares no version and `Cargo.toml` says `0.1.0`.
- Both images carry the same binary, sha256 `f6fa781d0a5a8f7141135c75a583178fd933a6714bac84aad27ad63403f97e94`.
- Both images build aai-cli from its default branch, and the source commit cannot be recovered from the binary.

Findings, per runtime:

| Question | Hermes (`terminal`) | OpenClaw (`exec`) |
|---|---|---|
| Exit code present | yes, `exit_code` inside the JSON string stored in `result` | yes, `result.details.exitCode`, with `details.status` `completed` |
| stdout and stderr merged | yes, both are in `output` | yes, both are in `details.aggregated` and `content[0].text` |
| `is_error` set on a non-zero exit | no, it is hardcoded `false` | no |
| Stored command wrapped in `sh -c` | no | no |
| Background run | `arguments.background = true` and `exit_code: 0` immediately | `arguments.background = true` and `details.status: "running"` |

- Every one of the 35 Tool Calls is stored as `SUCCESS`, including exits 2, 3 and 5, so the Tool Call status cannot tell success from failure.
- `agentbarn-message` commands ran, so the messaging plugins rewrote them, but telemetry stored the command before the rewrite.
- `aai-cli … | head -5` and `aai-cli … || true` exit `0` while aai-cli failed. Only the error envelope in the output shows the failure.
- A clap usage error (`aai-cli excel nonsense-command`) exits `2` with no error envelope.
- The pinned Hermes gateway fires `pre_gateway_dispatch` before `_is_user_authorized` (`gateway/run.py` at `v2026.8.19`), so the observer can mirror an inbound message that the allowlist then rejects.

Decision:
- Pre-flight ran on local k3d instead of staging. It answers every structural question, but not how many Hermes results arrive without a call id in real traffic. Run this on staging to size that undercount:

```sql
SELECT count(*)
FROM tool_call
WHERE tool_name = 'terminal'
  AND status = 'PENDING'
  AND occurred_at < now() - interval '1 hour';
```

Follow-up:
- Neither telemetry plugin sets `is_error` from the exit code. Fixing that is a separate runtime plugin ticket, because it moves the runtime digest and marks every running Agent as "Update available".
