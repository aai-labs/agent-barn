# Business value measurement — change log

Status: Active
Epic: Business value measurement
Related context: [Activity and Ingest](../activity-and-ingest.md), [Agent Activity](../agent-activity.md), [RBAC implementation brief](../rbac/IMPLEMENTATION-BRIEF.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: pre-flight evidence and real Hermes and OpenClaw result fixtures. Also delivered: the code-owned aai-cli command catalogue in `api/domains/business_value/catalogue.py`, with a drift test against the bundled references.
- In transition: nothing is captured yet. Business Actions are not recorded until the classifier, table, Ingest recording, and backfill slices land.
- Next: AF-344 classifier, then table and repository, Ingest recording and metric, and backfill.
- Blockers: the product owner has not signed off the default minutes per Outcome Type. They are placeholders until then.

## Slice history

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
