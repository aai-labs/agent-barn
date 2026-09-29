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
- Also delivered: the `organization_value_settings` and `organization_outcome_minutes` tables (migration `1045836844da`). Nothing reads or writes them yet.
- Also delivered: the `organization.value_settings.changed` Domain Event, registered and projected to the security audit. Nothing emits it yet.
- Also delivered: the pure valuation rules in `api/domains/business_value/service.py` (effective minutes, value, the value-to-spend ratio, and write categories). Nothing calls them yet.
- Also delivered: `ValueSettingsRepository`, which saves value settings and stages `organization.value_settings.changed` in one transaction.
- Also delivered: `GET` and `PUT /organizations/{organization_id}/value-settings`. The feature doc's [Value settings](../business-value.md#value-settings) section is the contract.
- In transition: AF-345 is landing in slices. Value settings are complete; the Organization value KPI is not yet built.
- Next: the Business Action aggregate reads the KPI needs.
- Blockers: the product owner has not signed off the default minutes per Outcome Type. They are placeholders until then.

## Slice history

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
