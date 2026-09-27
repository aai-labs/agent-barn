# Business Value

## Read when

Read before changing how Agent Barn derives Business Actions from Tool Calls, the aai-cli command catalogue, Outcome Types or their default minutes, the `business_action` table, the `agentbarn_business_actions` metric, or any read that reports value from Business Actions.

## Role in the system

Business Value measures what an Agent actually did rather than what it says it did. Every aai-cli command an Agent runs through a shell tool reaches Ingest as a Tool Call: Hermes reports `terminal` calls and OpenClaw reports `exec` calls, both with `arguments.command`. Ingest classifies each completed Tool Call on the server into content-free Business Actions and stores them in the same transaction. No runtime image or plugin release is involved, and both runtimes are covered at once.

This is not the per-Agent Activity tab ([`agent-activity.md`](agent-activity.md)). Activity reads billed model calls to show when an Agent was working. Business Value reads Tool Calls to show which business actions the Agent completed.

## Invariants

- A Business Action records only these fields:
  - `integration`: the aai-cli command group, for example `jira` or `microsoft`. This is not the glossary's **Integration**.
  - `resource` and `verb`
  - `is_write` and `outcome_type`
  - `status`
  - its position in the command (`ordinal`)
  - the Tool Call's timing and tenancy

  It never stores arguments or results.
- An action is **unclassified** when `is_write IS NULL` (the path is not in the catalogue), or when it is a write with `outcome_type IS NULL` (a passthrough `request` write). Unclassified actions are never valued.
- Actions are unique per `(tool_call_id, ordinal)`. A retried result inserts nothing new, and the metric counts only rows actually inserted.
- The ordinal counts every aai-cli invocation in the command, including ignored ones. A later catalogue change therefore does not shift stored ordinals.
- Recording runs inside `IngestService._process_tool_calls`, right after `ToolCallRepository.complete()` returns a row, in a savepoint of the Tool Call batch's transaction.
  - A database error rolls back only that savepoint, so the Tool Call batch still commits.
  - A classifier error is logged with the Tool Call id and skipped.
  - Neither path logs command text.
- Ingest writes Business Actions under the same Agent identity and ingest-key authentication as Tool Calls. There is no product read endpoint yet. Any future read must follow [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md).
- The catalogue lives in `api/domains/business_value/catalogue.py`, outside `aai_cli_skills/bundled/`, so catalogue changes do not move the runtime digest. `outcome_type` is a plain `VARCHAR(64)`, so catalogue changes need no migration.

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

Every write path in the catalogue maps to exactly one Outcome Type; there are 90 today. **The default minutes are placeholders until the product owner signs them off.** The sign-off is tracked as a blocker in [`business-value/CHANGELOG.md`](business-value/CHANGELOG.md).

| Outcome Type | Default minutes | Covers (examples) |
|---|---|---|
| `PULL_REQUEST_OPENED` | 20 | github/bitbucket `prs create` |
| `DOCUMENT_AUTHORED` | 20 | confluence `pages create`/`update`, excel `workbook create` |
| `COMMENT_POSTED` | 5 | jira `issues comments create`, github `prs reviews create`, confluence `pages comments create` |
| `MESSAGE_SENT` | 5 | microsoft `mail send` |
| `MEETING_SCHEDULED` | 5 | microsoft `calendar events create` |
| `SPREADSHEET_UPDATED` | 5 | excel and microsoft excel writes to values, sheets, and table rows |
| `FILE_UPLOADED` | 2 | drive/microsoft/sharepoint `files upload`, jira/confluence `attachments upload` |
| `RECORD_CREATED` | 5 | jira issues/ideas/sprints, pipedrive records, `leads convert`, microsoft contacts/todo/planner |
| `RECORD_UPDATED` | 3 | issue and record updates, `prs close`/`decline`, `sprints issues add`, comment edits |
| `RECORD_DELETED` | 1 | any delete |

Deletes always map to `RECORD_DELETED`, including sheets, tables, and comments. Housekeeping commands are ignored and not stored: `microsoft auth login`/`status`, `hubspot health`, `hubspot events custom send`, and `hubspot conversations visitor-identification tokens create`.

## Known gaps

Each of these is an **undercount**, not a verdict on the Agent. The last one is a possible overcount.

- **Only aai-cli is counted.** Work an Agent does through other tools, other CLIs, or its own code is not a Business Action.
- **Only direct invocations are detected.** `timeout aai-cli …`, `xargs aai-cli …`, and scripts that call aai-cli are not seen. Invocations inside `$(…)`, inside `(…)`, or after `&` are recorded but never `SUCCESS`.
- **Orphaned results and calls that never complete are not counted.** `ToolCallRepository.complete()` returns `None` for a result without a matching call, and such calls stay `PENDING`. Hermes produces one whenever its hook lacks a tool call id. How often this happens in real traffic has not been measured. The CHANGELOG records the staging query that would size it.
- **Some commands are unclassified.** Command groups with no bundled reference are stored with `is_write` `NULL`: the aai-cli binary also ships `calendar`, `apollo`, `sheets`, and `slack`. So are paths the catalogue does not know.
- **aai-cli is unpinned.** Both runtime images build it from its default branch, and it has no `--version`, so the commands actually run can drift from the bundled references the catalogue is tested against.
- **Business Actions store no arguments and no results.** They say what kind of action happened, not to what or with which content.
- **Success is conservative.** Actions outside the segment the exit code covers, background runs, and multi-action failures that cannot be attributed are `UNKNOWN`, even when they succeeded.
  - With a single action, any failure in the command marks it `ERROR`, even when the failing segment was not aai-cli.
- **Inbound requests may be overcounted.** The pinned Hermes gateway fires `pre_gateway_dispatch` before its allowlist check, so the observer can mirror an inbound message the allowlist then rejects. Any report that counts inbound requests from mirrored messages may include them.

## Data flow

```text
Agent runtime ──→ Ingest API ──→ Tool Call repository (upsert pending, complete)
                                        ↓ completed row
                          classify(tool_call) → Business Action repository
                                        ↓ (savepoint, ON CONFLICT DO NOTHING)
                               business_action + agentbarn_business_actions
```

## Boundaries

Ingest owns authentication and the transaction. The Business Value domain owns the catalogue, the classifier, and `business_action` persistence. Tool Calls remain the audit record, and Business Actions are derived from them and cascade with them.

## Source map

| Concern | Authoritative source |
|---|---|
| Command catalogue and Outcome Types | `../../api/domains/business_value/catalogue.py` |
| Classifier and status inference | `../../api/domains/business_value/classifier.py` |
| Table and persistence | `../../api/domains/business_value/models.py`, `../../api/domains/business_value/repository.py`, migration `39ea6a8e2fe4` |
| Ingest wiring and metric | `../../api/domains/ingest/service.py`, `../../api/core/metrics.py` (`agentbarn_business_actions`) |
| Recorded runtime fixtures | `../../api/tests/fixtures/business_actions/` |
| Tests | `../../api/tests/unit/test_business_action_catalogue.py`, `../../api/tests/unit/test_business_action_classifier.py`, `../../api/tests/integration/test_business_action_repository.py`, `../../api/tests/integration/test_ingest.py` |

## Related decisions

- [`2026-09-25-classify-business-actions-at-ingest.md`](../adr/2026-09-25-classify-business-actions-at-ingest.md)
- Delivery state: [`business-value/CHANGELOG.md`](business-value/CHANGELOG.md)

## Change impact

- **A catalogue change** needs the drift test to pass. A catalogue that no longer matches the bundled references fails CI. The change applies only to Tool Calls completed after the deploy; rows already stored keep their earlier mapping.
- **A change to the Tool Call telemetry shape** (result format, exit code location, `is_error` semantics) must update the classifier's evidence rules and the recorded fixtures together.
- **A new read surface** over `business_action` must apply the RBAC brief and report `UNKNOWN` as unverified, never as value.
