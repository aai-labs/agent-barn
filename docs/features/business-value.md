# Business Value

## Read when

Read before changing how Agent Barn derives Business Actions from Tool Calls, the aai-cli or gog command catalogues, Outcome Types or their default minutes, the `business_action` table, the `agentbarn_business_actions` metric, or any read that reports value from Business Actions.

## Role in the system

Business Value measures what an Agent actually did rather than what it says it did. Every aai-cli or gog command an Agent runs through a shell tool reaches Ingest as a Tool Call: Hermes reports `terminal` calls and OpenClaw reports `exec` calls, both with `arguments.command`. aai-cli reaches most Integrations; gog reaches Google Workspace, the only way Agent Barn connects Gmail, Calendar, Drive, and Sheets ([`integrations.md`](integrations.md)). Ingest classifies each completed Tool Call on the server into content-free Business Actions and stores them in the same transaction. No runtime image or plugin release is involved, and both runtimes are covered at once.

This is not the per-Agent Activity tab ([`agent-activity.md`](agent-activity.md)). Activity reads billed model calls to show when an Agent was working. Business Value reads Tool Calls to show which business actions the Agent completed.

## Invariants

- A Business Action records only these fields:
  - `integration`: the aai-cli command group, for example `jira` or `microsoft`, or `google-<service>` for gog, for example `google-gmail`. The `google-` prefix keeps gog apart from aai-cli's own `drive` (Google Drive) and `email` (Zoho Mail) groups. This is not the glossary's **Integration**.
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
  - The Business Action counts and `CostRepository.spend_series` are built on the same `generate_series(date_trunc(...))` spine, so every bucket is present and the two merge by key.
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

## Known gaps

Each of these is an **undercount**, not a verdict on the Agent. The last one is a possible overcount.

- **Only aai-cli and gog are counted.** Work an Agent does through other tools, other CLIs, or its own code is not a Business Action. gog Tool Calls stored before gog classification was deployed are counted only once the operator backfill has run.
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
- It is operator-run only (`make backfill-business-actions` locally, or `kubectl exec` in a deployment) and runs unscoped under the RBAC brief's background-work exception.

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

Ingest owns authentication and the transaction. The Business Value domain owns the aai-cli and gog catalogues, the classifier, `business_action` persistence, and the Organization's value settings. How gog is installed and authenticated in the runtimes belongs to [`integrations.md`](integrations.md). Tool Calls remain the audit record, and Business Actions are derived from them and cascade with them. Value settings cascade with their Organization.

## Source map

| Concern | Authoritative source |
|---|---|
| Command catalogue and Outcome Types | `../../api/domains/business_value/catalogue.py` |
| gog command catalogue (paths, aliases, shortcuts, flags) | `../../api/domains/business_value/gog_catalogue.py` |
| Recorded gog command tree (pinned version) | `../../api/tests/fixtures/gog/command-tree.json` |
| Classifier and status inference | `../../api/domains/business_value/classifier.py` |
| Table and persistence | `../../api/domains/business_value/models.py`, `../../api/domains/business_value/repository.py`, migration `39ea6a8e2fe4` |
| Operator backfill | `../../api/domains/business_value/backfill.py`, `make backfill-business-actions` |
| Ingest wiring and metric | `../../api/domains/ingest/service.py`, `../../api/core/metrics.py` (`agentbarn_business_actions`) |
| Recorded runtime fixtures | `../../api/tests/fixtures/business_actions/` (aai-cli: `hermes.json`, `openclaw.json`; gog: `gog_hermes.json`, `gog_openclaw.json`, redacted) |
| Value settings tables, DTOs, and bounds | `../../api/domains/business_value/models.py`, migration `1045836844da` |
| Value settings persistence and audit event | `../../api/domains/business_value/repository.py` (`ValueSettingsRepository`), `../../api/domains/events/catalog.py` |
| Valuation rules, value settings, and the Organization value service | `../../api/domains/business_value/service.py` |
| Organization value aggregates | `../../api/domains/business_value/repository.py` (`BusinessActionRepository.category_counts`, `successful_counts_by_bucket`, `successful_counts_by_agent`) |
| HTTP routes | `../../api/domains/business_value/routes.py` |
| Test seeding | `../../api/tests/steps/business_action.py`, `../../api/tests/steps/cost.py` (`without_agent`) |
| Tests | `../../api/tests/unit/test_business_action_catalogue.py`, `../../api/tests/unit/test_gog_catalogue.py`, `../../api/tests/unit/test_business_action_classifier.py`, `../../api/tests/unit/test_metrics.py`, `../../api/tests/unit/test_business_value_valuation.py`, `../../api/tests/integration/test_business_action_repository.py`, `../../api/tests/integration/test_ingest.py`, `../../api/tests/integration/test_business_action_backfill.py`, `../../api/tests/integration/test_value_settings.py`, `../../api/tests/integration/test_organization_value.py`, `../../api/tests/integration/test_cross_org_isolation.py` |

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
