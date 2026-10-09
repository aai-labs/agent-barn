# Business Value

## Read when

Read before changing how Agent Barn derives Business Actions from Tool Calls, the aai-cli or gog command catalogues, Outcome Types or their default minutes, the `business_action` table, the `agentbarn_business_actions` metric, or any read that reports value from Business Actions. Also read before changing the Organization activity read, or what counts as a Request, a handled delivery, or a response time, and before changing the KPIs dashboard UI.

## Role in the system

Business Value measures what an Agent actually did rather than what it says it did. Every aai-cli or gog command an Agent runs through a shell tool reaches Ingest as a Tool Call: Hermes reports `terminal` calls and OpenClaw reports `exec` calls, both with `arguments.command`. aai-cli reaches most Integrations; gog reaches Google Workspace, the only way Agent Barn connects Gmail, Calendar, Drive, and Sheets ([`integrations.md`](integrations.md)). Ingest classifies each completed Tool Call on the server into content-free Business Actions and stores them in the same transaction. No runtime image or plugin release is involved, and both runtimes are covered at once.

This is not the per-Agent Activity tab ([`agent-activity.md`](agent-activity.md)). Activity reads billed model calls to show when an Agent was working. Business Value reads Tool Calls to show which business actions the Agent completed.

## Invariants

- A Business Action records only these fields:
  - `integration`: the aai-cli command group, for example `jira` or `microsoft`, or `google-<service>` for gog, for example `google-gmail`. The `google-` prefix keeps gog apart from aai-cli's own `drive` (Google Drive) group. The retired Zoho Mail `email` group is no longer catalogued. This is not the glossary's **Integration**.
  - `resource` and `verb`
  - `is_write` and `outcome_type`
  - `status`
  - its position in the command (`ordinal`)
  - the Tool Call's timing and tenancy

  It never stores arguments or results.
- An action is **unclassified** when `is_write IS NULL` (the path is not in the catalogue), or when it is a write with `outcome_type IS NULL` (a passthrough `request` write). Unclassified actions are never valued.
- Actions are unique per `(tool_call_id, ordinal)`. A retried result inserts nothing new, and the metric counts only rows actually inserted.
- The ordinal counts every aai-cli invocation in the command, including ignored ones, and then every gog invocation after them. A later catalogue change therefore does not shift stored ordinals, and neither did adding gog: an aai-cli action stored before gog was classified keeps its ordinal, and the backfill adds the gog actions after it.
- Recording runs inside `IngestService._process_tool_calls`, right after `ToolCallRepository.complete()` returns a row, in a savepoint of the Tool Call batch's transaction.
  - A database error rolls back only that savepoint, so the Tool Call batch still commits.
  - A classifier error is logged with the Tool Call id and skipped.
  - Neither path logs command text.
- Ingest writes Business Actions under the same Agent identity and ingest-key authentication as Tool Calls. Every product read follows [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md); see [Value settings](#value-settings) for the Organization-authorized surface.
- The aai-cli catalogue lives in `api/domains/business_value/catalogue.py` and the gog catalogue in `api/domains/business_value/gog_catalogue.py`, both outside `aai_cli_skills/bundled/`, so catalogue changes do not move the runtime digest. `outcome_type` is a plain `VARCHAR(64)`, so catalogue changes need no migration.
- The gog catalogue describes the gog binary pinned in both runtime images (`GOG_VERSION` in `hermes-base/Dockerfile` and `openclaw-base/Dockerfile`, 0.37.0 today). Unlike aai-cli, gog is pinned, and its command tree is recorded from that binary in `api/tests/fixtures/gog/command-tree.json`.

## Classification

The classifier (`api/domains/business_value/classifier.py`) is a pure function of the stored Tool Call. It works in this order:

1. Unwrap `AGENTBARN_TOOL_SESSION=… AGENTBARN_TOOL_INVOCATION=… sh -c '<command>'` when the whole command has that shape.
2. Split the command into segments on `&&`, `||`, `|`, `;`, `&`, newlines, and subshell parentheses. Quoted text stays intact.
3. Treat a segment as an invocation when its executable, after any `VAR=value` assignments, has basename `aai-cli`.
4. Drop the global flags `--profile`, `--config`, `--secrets-file`, and `--key-file` with their values, in both `--flag VALUE` and `--flag=VALUE` form and in any position.
5. Ignore any invocation that has `--help` or `-h`, a `help` subcommand, or no command path, and any invocation in the aai-cli tooling groups `config`, `skills`, `secrets`, or `help`. `--version` is not a help flag, because `confluence pages update` takes `--version N`.
6. Match the longest known command path. `verb` is its last token and `resource` is the tokens in between.
   - Passthrough `request` commands (microsoft, pipedrive, hubspot, openpanel) read their HTTP method: `get` and `head` are reads, and any other method is a write with no Outcome Type.
   - An unknown path keeps the deepest known resource. It keeps the next token as `verb` only if that token looks like a command word, so no argument text is stored.

### gog commands

A segment whose executable has basename `gog` is classified with the gog catalogue. It uses the same unwrapping and segmentation, and these rules:

1. **Flags.** Global flags that take a value (`-a`/`--account`, `--client`, `--home`, `--access-token`, `--color`, `--select`, `--enable-commands`, `--enable-commands-exact`, `--disable-commands`) are dropped with their value. Every other `-`-prefixed token is skipped while the command path is read.
2. **Ignored invocations.** An invocation is ignored when it:
   - has `--help`/`-h`, a `help` subcommand, or no command path;
   - is a dry run: `-n`, `--dry-run`, or `--dry-run=<value>` other than `false`/`0`. A dry run exits 0 and prints the intended request, so counting it would record a write that never happened. This was observed on gog 0.37.0.
   - is gog tooling: `auth`, `config`, `schema`, `version`, `status`, `whoami`, `login`, `logout`, and the other entries of `GOG_IGNORED_COMMANDS`;
   - is a catalogue entry marked ignored, such as `gmail settings watch …` or `calendar alias …`.
3. **Aliases.** Aliases resolve to the canonical path, e.g. `mail`/`email` → `gmail`, `drv` → `drive`, `ls` → `list`, and top-level shortcuts such as `gog send` → `gmail send` or `gog upload` → `drive upload`.
4. **Granted services.** A command for `gmail`, `calendar`, `drive`, or `sheets` (the services a Google Workspace credential can grant) is matched against the catalogue like aai-cli.
   - `integration` is `google-<service>`, `verb` is the last path token, and `resource` is the tokens in between.
5. **Other services.** A command for another Google service, such as `docs` or `tasks`, is stored as unclassified with `integration` `google-<service>`.

gog has no error envelope; its errors are plain text on stderr. Its status therefore comes from the exit code alone, under the table below.
- Exit `3`, gog's opt-in `--fail-empty` "no results", is read as `0` when the whole command is a single gog invocation.
- Anywhere else, exit `3` is failure evidence, because in a chain it may have stopped later commands from running.

Status is inferred from the result, never from the Tool Call's own status. Both runtimes report `is_error: false` on a non-zero exit, so every stored shell Tool Call reads `SUCCESS`.

| Status | When |
|---|---|
| `ERROR` | Failure evidence exists and the action is the only one in the Tool Call, or it is the only action whose `integration` matches the single error envelope's `service`. |
| `SUCCESS` | Exit code `0` with no failure evidence, and the exit code covers the action: the whole command is an `&&` chain, or the action is in the last segment. |
| `UNKNOWN` | Anything else: no exit evidence, a background run, an action outside the covered segment, or a multi-action failure that cannot be attributed. `UNKNOWN` never carries value. |

Failure evidence is any of the following:

- the aai-cli error envelope, a JSON line with `code`, `message`, `operation`, and `service`, which **overrides a zero exit** because `| head` and `|| true` hide aai-cli's exit status
- a non-zero exit code
- a Hermes `error` or `blocked` / `pending_approval` status
- a runtime-reported error

Exit evidence comes from different places in each runtime:

- Hermes: `exit_code` inside the JSON string stored in `result`.
- OpenClaw: `result.details.exitCode`, used only when `details.status` is `completed`.

## Outcome Types

Every write path in both catalogues maps to exactly one Outcome Type: 90 aai-cli paths and 109 gog paths today. gog writes use the same 10 Outcome Types. **The default minutes are placeholders until the product owner signs them off.** The sign-off is tracked as a blocker in [`business-value/CHANGELOG.md`](business-value/CHANGELOG.md).

| Outcome Type | Default minutes | Covers (examples) |
|---|---|---|
| `PULL_REQUEST_OPENED` | 20 | github/bitbucket `prs create` |
| `DOCUMENT_AUTHORED` | 20 | confluence `pages create`/`update`, excel `workbook create`, gog `sheets create` |
| `COMMENT_POSTED` | 5 | jira `issues comments create`, github `prs reviews create`, confluence `pages comments create`, gog `drive comments create`/`reply` |
| `MESSAGE_SENT` | 5 | microsoft `mail send`, gog `gmail send`/`reply`/`reply-all`/`forward`/`autoreply`/`drafts send` |
| `MEETING_SCHEDULED` | 5 | microsoft `calendar events create`, gog `calendar create`/`focus-time`/`out-of-office` |
| `SPREADSHEET_UPDATED` | 5 | excel and microsoft excel writes to values, sheets, and table rows; gog `sheets` writes, including `clear` |
| `FILE_UPLOADED` | 2 | drive/microsoft/sharepoint `files upload`, jira/confluence `attachments upload`, gog `drive upload`/`sync push` |
| `RECORD_CREATED` | 5 | jira issues/ideas/sprints, pipedrive records, `leads convert`, microsoft contacts/todo/planner, gog Gmail drafts/labels/filters, `drive mkdir`/`copy` |
| `RECORD_UPDATED` | 3 | issue and record updates, `prs close`/`decline`, `sprints issues add`, comment edits, gog label/read-state changes, `drive share`/`move`/`rename`, `calendar update`/`respond` |
| `RECORD_DELETED` | 1 | any delete, including gog `gmail trash` and `drive delete` (which moves to trash) |

Deletes always map to `RECORD_DELETED`, including sheets, tables, and comments. Housekeeping commands are ignored and not stored:
- aai-cli: `microsoft auth login`/`status`, `hubspot health`, `hubspot events custom send`, and `hubspot conversations visitor-identification tokens create`;
- gog: the tooling commands above, `gmail settings watch …`, `gmail track setup`/`status`/`key rotate`, `gmail settings sendas verify`, `drive changes serve`/`watch`/`stop`, and `calendar alias …`.

## Value settings

An Organization turns Business Actions into time and money through its value settings.

- **Rate.** An hourly rate in USD, with no platform default. Until it is set, value is not reported.
- **Minutes.** The minutes saved per Outcome Type. Each defaults to the catalogue value above. An Organization may override any Outcome Type; an explicit `null` reverts it to the default.

`GET` and `PUT /organizations/{organization_id}/value-settings`:

- **Read (`ValueSettingsRead`).**
  - `hourly_rate_usd` is a float, or `null` while unset.
  - One row per catalogue Outcome Type, in catalogue order, with `default_minutes`, `override_minutes`, `effective_minutes`, and `source` (`default` or `override`).
  - A stored override for an Outcome Type that is no longer in the catalogue is ignored.
- **Update (`ValueSettingsUpdate`, `extra="forbid"`).**
  - `hourly_rate_usd`: omitting it leaves the rate unchanged; `null` clears it. The rate is a decimal with at most two places, from 0 to `MAX_HOURLY_RATE_USD` (10,000.00). It is stored as `NUMERIC(12,2)`.
  - `outcome_minutes`: a map from Outcome Type to minutes. A missing key is unchanged; `null` reverts to the default.
  - Minutes must be JSON integers from 1 to `MAX_OUTCOME_MINUTES` (1,440). Strings, floats, and booleans are rejected.
  - An unknown Outcome Type returns 422, as does any other validation failure.
- **Authorization.**
  - Reads require both `cost.read` and `activity.read`, because value mixes spend with Agent activity. This is the pairing Agent Activity uses.
  - Writes require `organization.update`.
  - Both go through `PermissionPolicy.require_organization`, so Owners and Admins pass, and a Member gets 403.
  - A non-member gets 403 from the Organization path check, like every Organization-scoped route. So does a Platform Administrator without a Membership.
- **Audit.** A save that changes anything emits `organization.value_settings.changed` through the outbox, in the same transaction as the settings rows. After commit it is enqueued for the security-audit projection.
  - `field_changes` is keyed `hourly_rate_usd` or `outcome_minutes.<OUTCOME_TYPE>`. Each entry holds `previous` and `current` as strings: the rate to two places, minutes as an integer, and `null` for unset or default.
  - A save that changes nothing, including the same rate spelled differently, emits nothing.
  - **Concurrent saves are serialized.** The diff is computed inside the transaction that writes it:
    - every save first ensures the Organization's settings row exists (`INSERT … ON CONFLICT DO NOTHING`), then locks it (`SELECT … FOR UPDATE`) before reading the rate and overrides;
    - a save that overlaps another waits for it and records the values that save committed, so each audit entry matches what it actually replaced;
    - two first saves no longer collide on the unique row.
  - A settings row whose `hourly_rate_usd` is `NULL` means no rate is set, the same as having no row. The first save that addresses anything creates it, even if it only changes minutes.

## Organization value

`GET /organizations/{organization_id}/value` sets an Organization's Business Actions against its LLM spend.

### Window and authorization

- The window comes from `get_stats_window` (`period`, `from_date`, `to_date`, `granularity`). It is half-open, `[start, end)`, on `business_action.occurred_at` and `cost_record.occurred_at`, and the response echoes it.
- Authorization is the same as reading value settings:
  - It requires both `cost.read` and `activity.read`.
  - The Organization-level scope from that check feeds `agent_scope_predicates(scope, include_deleted=True)`, so a soft-deleted Agent's work still counts.

### Valuation at read time

Figures are computed when read. Changing the rate or an override therefore changes past figures too.

- The repository returns counts grouped by Outcome Type.
- The service applies the effective minutes and the rate in `Decimal`: `value = minutes × rate ÷ 60`.
- Values are emitted as floats, following the Costs convention.

### Write categories

Each Business Action falls in exactly one category. A write is **classified** when its Outcome Type is in the current catalogue.

| Category | Rule | Valued |
|---|---|---|
| Successful | classified, `SUCCESS` | yes |
| Unverified | classified, `UNKNOWN` | no |
| Failed | classified, `ERROR` | no |
| Unclassified | any status: `is_write IS NULL`, a write with no Outcome Type, or an Outcome Type no longer in the catalogue | no |

- Reads are not counted.
- Hermes never reports errors, so many of its writes are `UNKNOWN`. The unverified count exists so a low value can be explained rather than shown as a silent $0.

### Spend

- Spend is read through `CostRepository` with an Organization-only `CostFilter`. It has no Agent join, so the total matches the Costs page.
  - Spend from a soft- or hard-deleted Agent stays in the total, because `cost_record` has no foreign keys.
- Spend with no Organization attribution is never in any Organization's total.
  - The cost sync attributes all-or-nothing (`costs/sync.py`), so a row carries both `agent_id` and `organization_id`, or neither.
  - The per-Agent `"Unattributed"` row therefore appears only for a cost row that has an Organization but no Agent. The sync does not write such rows today.

### Response

- **`totals`:**
  - `successful_writes`, `minutes_saved`, `value`, `spend`, and `value_to_spend_ratio`
  - `unverified_writes`, `failed_writes`, and `unclassified_actions`
  - `hourly_rate_usd`, the rate used
- **`series`:** one point per UTC bucket, with `bucket`, `minutes_saved`, `value`, and `spend`.
  - The bucket spine is the one `CostRepository.spend_series` builds with `generate_series(date_trunc(...))`, so every bucket is present.
  - Business Action counts are grouped by the same UTC `date_trunc(...)` key and looked up on that spine; a bucket with no successful writes reads as zero.
  - Buckets are emitted as UTC instants.
- **`agents`:** a full outer merge of the per-Agent Business Action counts with `CostRepository.spend_by_agent`.
  - Each row carries `agent_id`, `agent_name`, `agent_deleted`, `successful_writes`, `minutes_saved`, `value`, `spend`, and `value_to_spend_ratio`.
  - Names come from `AgentRepository.find_all_for_org`, which includes deleted Agents. A hard-deleted Agent falls back to the cost record's name, with `agent_deleted` true.
  - A null `agent_id` is labelled `"Unattributed"`.
  - Rows are ordered by minutes saved, then spend, both descending.
- **`top_outcome_types`:** each catalogue Outcome Type with at least one successful write.
  - Each entry carries `successful_writes`, `effective_minutes`, `minutes_saved`, and `value`.
  - Entries are ordered by minutes saved, then count, both descending.

### Nulls

- With no rate set, every `value` and ratio is `null`, while minutes and spend are still reported.
- A ratio is also `null` when its spend is zero.

## Organization activity

`GET /organizations/{organization_id}/value/activity` shows how much work each Agent handles, how reliably and quickly it responds, and what each Request costs. It explains why an Agent is or is not producing value.

This is not the per-Agent Activity tab ([`agent-activity.md`](agent-activity.md), `api/domains/activity`), which groups one Agent's billed model calls into wakes and is unchanged.

### Window and authorization

- The window is the same `get_stats_window` as [Organization value](#organization-value): half-open `[start, end)` and echoed in the response.
- Authorization is also the same. It requires both `cost.read` and `activity.read` through `PermissionPolicy.require_organization`, so a Member gets 403 and so does a non-member.
- Every aggregate joins `agent` with `agent_scope_predicates(scope, include_deleted=True)`, so a soft-deleted Agent stays in the periods it worked.
- `agent_chat_message` has no `organization_id` column, so it is scoped only through that Agent join. The other tables also filter on their own `organization_id`.

### Metrics

Each metric is named for what the data proves.

| Metric | Definition | Time column |
|---|---|---|
| **Requests** | Inbound Conversation Messages (`agent_chat_message`, direction INBOUND), which include native-runtime transcripts and Web Chat, plus every `webhook_invocation` row of any status. A Webhook Invocation writes no Conversation Message, so nothing is counted twice. | message `occurred_at`; invocation `created_at` |
| **Handled without failure** | SUCCEEDED ÷ (SUCCEEDED + DEAD_LETTERED + UNAVAILABLE) over INBOUND Communication Deliveries. CANCELLED, PENDING, and PROCESSING are left out. Returned with `handled_coverage`, the denominator. | `completed_at` |
| **Median response time** | `percentile_cont(0.5)` of `completed_at − created_at`, in seconds, over SUCCEEDED INBOUND deliveries with `attempt_count = 1`. Returned with `response_time_coverage`, the number of such deliveries. | `completed_at` |
| **Cost per Request** | Organization LLM spend (`CostRepository`, Organization-only `CostFilter`, as in [Spend](#spend)) ÷ Requests. | cost `occurred_at` |
| **Tool Calls per Request** | Tool Calls of any status ÷ Requests. | tool call `occurred_at` |

What the delivery statuses mean:
- UNAVAILABLE means the message arrived while the Agent was not running. It is set only when the delivery is accepted, so it counts as a failure.
- SUCCEEDED means the runtime completed its run, not that the reply was correct.
- An INBOUND delivery that fails in a retryable way, including a lease expiry, returns to PENDING on the same row and keeps its `attempt_count`. Only a claim raises that count.
  - It counts once, at its final status.
  - If it ends SUCCEEDED, it is handled but left out of the median, which times first attempts only.
  - Only OUTBOUND deliveries can be retried by hand, and DEAD_LETTERED is final for an INBOUND delivery.
- The response time includes queue wait and any command-approval wait. No approval stage is stored, so the two cannot be separated.

### Coverage

- Only gateway-owned Connections create new Communication Deliveries. Ownership follows the [fixed Platform contract](../architecture/runtime-and-deployment.md#platform-plugin-boundary) in every environment; deployment allowlists no longer change coverage.
- Native traffic is mirrored into `agent_chat_message` through Ingest but has no delivery rows. Web Chat and Email always create them.
- The handled rate and the response time therefore cover only part of the Requests. Each is returned with its coverage count, so the dashboard can say "based on 120 of 480 requests".
- Gateway ingress and runtime callbacks reject native transport. Historical deliveries created before the cutoff remain readable and cannot be claimed or revived by expired-lease recovery. Stranded PENDING rows and the CANCELLED rows produced by the [native delivery retirement migration](../architecture/runtime-and-deployment.md#connection-failure-recovery) remain outside the handled-rate denominator.

### Response

- **`totals`** (`ActivityTotalsRead`):
  - `requests`
  - `handled_without_failure_rate` and `handled_coverage`
  - `median_response_seconds` and `response_time_coverage`
  - `cost_per_request` and `tool_calls_per_request`
- **`requests_series`:** `bucket` and `requests` for each UTC bucket.
  - It comes from `ConversationRepository.daily_direction_counts_since(..., organization_id=scope.organization_id)` for inbound messages, plus `ValueActivityRepository.webhook_invocations_by_bucket`.
  - Both use the same `generate_series(date_trunc(...))` spine as `CostRepository.spend_series`, and every bucket is emitted as a UTC instant.
  - Totals equal the sum of the series.
- **`agents`:** one row for every Agent with Requests, deliveries, Tool Calls, or spend.
  - Each row carries the same figures, plus `agent_id`, `agent_name`, `agent_deleted`, and `spend`.
  - Names and the `"Unattributed"` row follow [Organization value](#organization-value).
  - Rows are ordered by Requests, then spend, both descending.

### Nulls

- Every rate, median, and per-Request figure is `null` when its denominator is zero.
- Zero spend over some Requests is a cost per Request of `0.0`.

### Caveats

- **Scheduled runs are not Requests.** A cron run leaves no Request, but its Tool Calls and spend still count. Cost per Request and Tool Calls per Request therefore include background work.
- **An approval answer is a Request.** Answering a command approval in Web Chat sends a new inbound message and delivery.
- **Webhook Invocations without an event id are never deduplicated.** Each one is its own row, and so its own Request.
- **Inbound messages may be overcounted** on Hermes, as described in [Known gaps](#known-gaps).

## KPI dashboard

The Organization's KPIs page, `/dashboard/{organization_id}/kpis`, renders value settings, the Organization value, and Organization activity on one page. It reads only the three endpoints above.

### Access

- The page is for Owners and Admins. The "KPIs" navigation entry sits right after Costs, inside the same `canManage` check, so desktop and the mobile drawer both hide it from Members.
- The page gates with `useRequireOrgManager`, as Costs does. A Member who opens the URL is redirected to the Organization's home, and the dashboard never mounts, so it sends no value or activity read.

### Date range

- One date range drives every figure. `from` and `to` live in the page URL, as on Costs, and are sent as `from_date` and `to_date`.
- With no range chosen, neither is sent, so the server's 30-day default applies. The page shows the window each response echoes.

### Headline tiles

| Tile | Source | Shown |
|---|---|---|
| Hours saved | `/value` `totals.minutes_saved` | Hours to one decimal; a non-zero figure under 0.05 h reads "<0.1 h". Hint: the successful write count. |
| Value | `/value` `totals.value` | USD, with the rate used as the hint. |
| LLM spend | `/value` `totals.spend` | USD, with a "View in Costs" link carrying the same `from` and `to`. |
| Value per dollar spent | `/value` `totals.value_to_spend_ratio` | "$X.XX per $1"; a non-zero ratio under $0.005 reads "<$0.01 per $1". |
| Requests | `/value/activity` `totals.requests` | A count. |
| Handled without failure | `/value/activity` `totals.handled_without_failure_rate` | A percentage, with one decimal below 0.5% and from 99.5% up to 100%, so a real failure never rounds to 100% and a real success never rounds to 0%. Hint: "based on {handled_coverage} of {requests} requests routed through Agent Barn". It names no channels, because which ones are routed depends on the environment's `COMMUNICATIONS_NATIVE_PLATFORMS`. |

The dashboard never shows `$0` or `0%` for an unknown figure:

- With no hourly rate set, Value and Value per dollar read "Set an hourly rate".
- Any other null, such as the ratio when spend is zero, or the handled rate without deliveries, reads "not enough data".
- A missing figure shows "—" with its reason on the line below, so the reason is never cut off.

Each tile has a clickable information button with its calculation and scope. The hints work with a mouse, keyboard, or touch. Hours saved is labelled as an estimate: it sums successful actions × effective minutes per Outcome Type, then divides by 60. Value is hours saved × hourly rate; Value per dollar is value ÷ LLM spend, with a worked example and the missing-rate/zero-spend requirements. The other hints explain the spend, Request, and handled-rate inputs.

Each tile belongs to one endpoint. If an endpoint fails, only its tiles show "Unable to load" with a Retry; the other endpoint's tiles still render.

### Trend chart

- One chart with two tabs, labelled by the bucket granularity each response echoes.
  - **Value vs spend** (the default) draws `/value` `series`: value and spend per bucket.
  - **Requests** draws `/value/activity` `requests_series`.
- The Value vs spend tab labels the figures as estimated value and recorded LLM spend per interval, using the echoed granularity. Its information button explains that each point is the interval's hours saved × hourly rate and recorded LLM costs, with separate amounts per interval rather than cumulative totals.
- With no hourly rate set, every value point is null, so the chart draws spend alone and says "Set an hourly rate to chart value".
- Each tab belongs to one endpoint. A failed endpoint shows "Unable to load" with a Retry inside its own tab, and the other tab still renders.

### Agents table

- One row per Agent in either response, merged on `agent_id`.
  - A null `agent_id` is the "Unattributed" row, and only that row carries the name.
  - Otherwise the name comes from `/value`, then `/value/activity`. A hard-deleted Agent with no stored name reads "Deleted agent".
  - A row whose `agent_deleted` is true in either response carries a "Deleted" badge.
- An Agent that one response omits had nothing to report there: `/value` lists every Agent with a successful write or spend, and `/value/activity` every Agent with Requests, deliveries, Tool Calls, or spend. Its figures from that response read as zero, and its rates as "not enough data".
- Columns: Agent, Value, Hours saved, LLM spend, Value per dollar, Requests, Handled without failure, Median response, Cost per request, and Tool calls per request.
  - The handled rate and the median response show their coverage, the `handled_coverage` and `response_time_coverage` counts, for example "75% · 100 reqs" and "1.5 s · 80 reqs".
  - The response time reads "<1 s", "1.5 s", "2m 05s", or "1h 02m".
  - Null figures follow the same wording as the tiles.
- Rows open sorted by hours saved, descending. Every column sorts, a second click reverses it, and unknown figures stay last in both directions.
- A failed endpoint, including a failed refetch after a successful read, shows "—" in its own columns and one "Unable to load … figures" line with a Retry above the table.

### Footnotes

- "Top outcomes" lists `/value` `top_outcome_types` in the server's order. Each entry shows its label, its successful write count, its hours, and its value. Labels are derived from the Outcome Type code (`PULL_REQUEST_OPENED` reads "Pull request opened"), so a new catalogue Outcome Type needs no UI change.
- The unverified write and unclassified action counts from `/value` `totals`.
- A fixed note: value counts only successful aai-cli and gog write actions, and the handled rate and response time cover only requests routed through Agent Barn, while natively connected channels count as Requests but are not timed.

### Empty and loading states

- **Empty.** When both responses arrive and both list no Agents, a card replaces the chart and table. It explains that value comes from successful aai-cli and gog write actions, and activity from messages and webhook invocations. The tiles and footnotes still show the period's zero counts.
- **Loading.** Each section has its own skeleton:
  - a tile skeleton while its endpoint is loading;
  - a chart skeleton in a tab whose endpoint is loading;
  - a table skeleton until both endpoints have answered, so a still-loading endpoint is not shown as "—" like a failure.

### Value settings modal

- A "Value settings" button opens a centered modal over the dashboard, with a scrollable form and a footer that stays visible on smaller screens. It reads `GET …/value-settings` only while open.
- The modal states that changes recalculate every figure on the page, including past periods. Inline guidance explains the hourly rate as the estimated cost of human work and minutes per outcome as adjustable assumptions, rather than measured working time.
- **Hourly rate (USD).** Empty means no rate. Otherwise it must be from 0 to 10,000 with at most two decimals, the bounds of [Value settings](#value-settings).
- **Minutes per Outcome Type,** in catalogue order. Each row shows a "Default" or "Custom" badge.
  - Editing a row makes it Custom.
  - "Reset to default (N min)" returns a Custom row to its default.
  - Minutes must be a whole number from 1 to 1,440.
- The editing session captures its settings and baseline together. A background refetch never changes that baseline or clears the draft; Save sends only the fields the user changed. Reopening starts a new session from the stored settings.
- Invalid fields show an inline error, and Save stays disabled while any field is invalid or nothing has changed.
- Closing with unsaved edits, by Cancel, the close button, Escape, or the overlay, asks "Discard unsaved changes?" through `ConfirmationDialog`. Cancel there keeps the edits, and Discard closes the modal. The next open starts again from the stored settings.
- A failed settings read shows an inline error with a Retry inside the modal.
- **Saving.**
  - Save sends `PUT …/value-settings` with only the fields that changed: `hourly_rate_usd` (`null` for an emptied rate) and `outcome_minutes` keyed by Outcome Type (`null` for a reset row).
  - On success the modal closes, and the Organization value and value settings refetch. Activity does not, because value settings never change it.
  - The dashboard then shows every figure recalculated at the new settings, past periods included.
  - On failure the server's message shows as a toast, and the modal stays open with the edits.

## Known gaps

Each of these is an **undercount**, not a verdict on the Agent. The last one is a possible overcount.

- **Only aai-cli and gog are counted.** Work an Agent does through other tools, other CLIs, or its own code is not a Business Action. gog Tool Calls stored before gog classification was deployed are counted once the deploy's backfill Job has run.
- **gog failures are easier to hide than aai-cli failures.**
  - gog prints no error envelope, so nothing overrides an exit code that another command hides.
  - Observed on OpenClaw: an Agent appended `; echo "EXIT_CODE:$?"` on its own. That makes gog's exit status invisible to the Tool Call, so the action is `UNKNOWN` rather than `SUCCESS` or `ERROR`.
  - Expect a higher unverified share for gog than for aai-cli. How often Agents do this has not been measured.
- **Only direct invocations are detected.** `timeout aai-cli …`, `xargs aai-cli …`, and scripts that call aai-cli are not seen. Invocations inside `$(…)`, inside `(…)`, or after `&` are recorded but never `SUCCESS`.
- **Orphaned results and calls that never complete are not counted.** `ToolCallRepository.complete()` returns `None` for a result without a matching call, and such calls stay `PENDING`. Hermes produces one whenever its hook lacks a tool call id. How often this happens in real traffic has not been measured. The CHANGELOG records the staging query that would size it.
- **Some commands are unclassified.** Command groups with no bundled reference are stored with `is_write` `NULL`: the aai-cli binary also ships `calendar`, `apollo`, `sheets`, and `slack`. So are paths the catalogue does not know.
- **aai-cli is unpinned.** Both runtime images build it from its default branch, and it has no `--version`, so the commands actually run can drift from the bundled references the catalogue is tested against. gog is pinned, and its catalogue is tested against the recorded command tree of the pinned version.
- **Business Actions store no arguments and no results.** They say what kind of action happened, not to what or with which content.
- **Success is conservative.** Actions outside the segment the exit code covers, background runs, and multi-action failures that cannot be attributed are `UNKNOWN`, even when they succeeded.
  - With a single action, any failure in the command marks it `ERROR`, even when the failing segment was not aai-cli.
- **Inbound requests may be overcounted.** The pinned Hermes gateway fires `pre_gateway_dispatch` before its allowlist check, so the observer can mirror an inbound message the allowlist then rejects. Any report that counts inbound requests from mirrored messages may include them.

## Backfill

`api/domains/business_value/backfill.py` classifies Tool Calls stored before Ingest recorded Business Actions, and brings stored rows in line after a catalogue change.

- It walks completed `terminal`/`exec` Tool Calls in id-keyset batches and infers status from content.
- Per Tool Call, keyed on `(tool_call_id, ordinal)`, it never changes `status`. It:
  - inserts missing rows
  - updates `integration`, `resource`, `verb`, `is_write`, and `outcome_type` only where the mapping changed
  - deletes rows the catalogue no longer produces
- Ordinals stay stable when a path becomes ignored, so the deletes remove exactly the stale rows and a now-ignored write stops being valued.
- A Tool Call whose classification fails keeps its rows.
- The `agentbarn-api` chart runs it as a Job on every install and upgrade. Locally, `make backfill-business-actions` runs it. It runs unscoped under the RBAC brief's background-work exception.

How to run it is in [`../guidelines/operations.md`](../guidelines/operations.md#business-action-backfill).

## Data flow

```text
Agent runtime ──→ Ingest API ──→ Tool Call repository (upsert pending, complete)
                                        ↓ completed row
                          classify(tool_call) → Business Action repository
                                        ↓ (savepoint, ON CONFLICT DO NOTHING)
                               business_action + agentbarn_business_actions
```

## Boundaries

Ingest owns authentication and the transaction. The Business Value domain owns the aai-cli and gog catalogues, the classifier, `business_action` persistence, and the Organization's value settings. How gog is installed and authenticated in the runtimes belongs to [`integrations.md`](integrations.md). Tool Calls remain the audit record, and Business Actions are derived from them and cascade with them. Value settings cascade with their Organization. For Organization activity, Business Value only reads: Conversation Message direction and occurrence time, INBOUND Communication Delivery outcomes and timestamps, Webhook Invocations, and Tool Calls. It writes nothing to them, and it never reads message, prompt, or tool content.

## Source map

| Concern | Authoritative source |
|---|---|
| Command catalogue and Outcome Types | `../../api/domains/business_value/catalogue.py` |
| gog command catalogue (paths, aliases, shortcuts, flags) | `../../api/domains/business_value/gog_catalogue.py` |
| Recorded gog command tree (pinned version) | `../../api/tests/fixtures/gog/command-tree.json` |
| Classifier and status inference | `../../api/domains/business_value/classifier.py` |
| Table and persistence | `../../api/domains/business_value/models.py`, `../../api/domains/business_value/repository.py`, migration `39ea6a8e2fe4` |
| Backfill | `../../api/domains/business_value/backfill.py`, `../../helm/agentbarn-api/templates/business-action-backfill-job.yaml`, `make backfill-business-actions` |
| Ingest wiring and metric | `../../api/domains/ingest/service.py`, `../../api/core/metrics.py` (`agentbarn_business_actions`) |
| Recorded runtime fixtures | `../../api/tests/fixtures/business_actions/` (aai-cli: `hermes.json`, `openclaw.json`; gog: `gog_hermes.json`, `gog_openclaw.json`, redacted) |
| Value settings tables, DTOs, and bounds | `../../api/domains/business_value/models.py`, migration `1045836844da` |
| Value settings persistence and audit event | `../../api/domains/business_value/repository.py` (`ValueSettingsRepository`), `../../api/domains/events/catalog.py` |
| Valuation rules, value settings, and the Organization value and activity service | `../../api/domains/business_value/service.py` (activity rules: `activity_figures`, `per_request`, `handled_rate`, `utc_bucket`) |
| Organization value aggregates | `../../api/domains/business_value/repository.py` (`BusinessActionRepository.category_counts`, `successful_counts_by_bucket`, `successful_counts_by_agent`) |
| Organization activity aggregates | `../../api/domains/business_value/repository.py` (`ValueActivityRepository`: inbound messages, webhook invocations, delivery outcomes, and tool calls, all scoped through the Agent join), served by migration `45bcefcb0749` (`ix_communication_delivery_agent_direction_completed`, `ix_agent_chat_message_agent_direction_occurred`) |
| HTTP routes | `../../api/domains/business_value/routes.py` |
| KPI dashboard UI | `../../ui/src/features/business-value/`, route `../../ui/src/app/dashboard/[orgId]/kpis/page.tsx`, navigation entry in `../../ui/src/components/top-nav.tsx` |
| KPI dashboard tests | `../../ui/tests/e2e/kpis.spec.ts`, `../../ui/tests/e2e/kpis-guidance.spec.ts`, `../../ui/tests/pages/kpis-page.po.ts` |
| Test seeding | `../../api/tests/steps/business_action.py`, `../../api/tests/steps/cost.py` (`without_agent`), `../../api/tests/steps/communication.py` (connections, deliveries, messages, webhook invocations, tool calls) |
| Tests | `../../api/tests/unit/test_business_action_catalogue.py`, `../../api/tests/unit/test_gog_catalogue.py`, `../../api/tests/unit/test_business_action_classifier.py`, `../../api/tests/unit/test_metrics.py`, `../../api/tests/unit/test_business_value_valuation.py`, `../../api/tests/integration/test_business_action_repository.py`, `../../api/tests/integration/test_ingest.py`, `../../api/tests/integration/test_business_action_backfill.py`, `../../api/tests/integration/test_value_settings.py`, `../../api/tests/integration/test_organization_value.py`, `../../api/tests/integration/test_organization_activity.py`, `../../api/tests/integration/test_cross_org_isolation.py` |

## Related decisions

- [`2026-09-25-classify-business-actions-at-ingest.md`](../adr/2026-09-25-classify-business-actions-at-ingest.md)
- Delivery state: [`business-value/CHANGELOG.md`](business-value/CHANGELOG.md)

## Change impact

- **A gog upgrade** (`GOG_VERSION` in either runtime Dockerfile) fails `test_gog_catalogue.py` until the command tree is re-recorded from the new binary (`gog schema --json`, pruned to names, aliases, one-line help, and global flags) and the catalogue is updated to match.
- **A catalogue change** needs the drift test to pass. A catalogue that no longer matches the bundled references, or the recorded gog command tree, fails CI.
  - It applies to Tool Calls completed after the deploy.
  - To bring rows already stored in line, re-mapping changed paths and removing paths that are now ignored, run the operator backfill (see [Backfill](#backfill)).
- **A change to the Tool Call telemetry shape** (result format, exit code location, `is_error` semantics) must update the classifier's evidence rules and the recorded fixtures together.
- **A new read surface** over `business_action` must apply the RBAC brief and report `UNKNOWN` as unverified, never as value.
- **A new Outcome Type** needs a `DEFAULT_MINUTES` entry and appears in value settings automatically. **Removing one** leaves any stored overrides in place; they are ignored on read.
- **A change to the value settings bounds or authorization** must update this document, `test_value_settings.py`, and the audit event's documentation in [`domain-events.md`](domain-events.md) together.
- **A change to the Costs read predicates** (`CostRepository._predicates`, `spend_series` buckets, or `spend_by_agent`) changes the Organization value's spend and series. Re-run `test_organization_value.py`.
- **A change to the Business Action status rules** moves actions between the successful, unverified, and failed categories, and so changes reported value.
- **A change to Communication Delivery statuses, `attempt_count` semantics, or native transport** changes the handled rate, the response time, or their coverage. Re-run `test_organization_activity.py`.
- **A change to Webhook Invocation admission or deduplication** changes the Request count.
- **A change to `ConversationRepository.daily_direction_counts_since`** changes the Request series. Its Organization caller relies on the unfiltered-`deleted_at` Agent join.
