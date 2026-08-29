# AF-273 — Communication diagnostics and recovery

## Summary

AF-273 adds connection-scoped communication diagnostics, an append-only operational journal, delivery lifecycle visibility, and safe recovery controls for Slack, Telegram, Discord, and Microsoft Teams.

The implementation keeps the page-level experience condensed and incident-oriented: connection health is summarized, recent failures expand into safe details, and delivery transitions remain the primary activity explorer. Raw provider-observation and policy-admission events remain available through the connection journal API rather than being promoted to another page-level table.

## What changed

### API and persistence

- Added the content-free `communication_operation_journal` model and migrations, including bounded retention.
- Added typed journal stages and inbound policy dispositions (`accepted`, `bot_ignored`, `mention_required`, `user_denied`, `channel_denied`, and `malformed_payload`).
- Added server-backed journal filtering, pagination, chronological per-delivery lifecycle reads, live delivery status enrichment, and Agent-scoped authorization predicates.
- Added connection diagnostics for provider health, reconnects, delivery counts, queue depth and age, latency, success rate, incidents, and recent failures.
- Added structured, redacted communication error details with safe category, operation, provider code, HTTP status, retryability, retry-after, and request ID fields.
- Added typed reconnect, retry, recovery, audit-event, and low-cardinality Prometheus metric paths.
- Preserved outbound ordering and stable idempotency identity across retries.

### UI

- Added the Communication Connection detail page and diagnostics surface.
- Added condensed health signals, incident grouping, safe failure-detail expansion, time-window filtering, paginated journal browsing, delivery status/direction badges, and per-delivery lifecycle drill-down.
- Added guarded reconnect and outbound dead-letter retry controls.
- Added the shadcn checkbox primitive used by the diagnostics filters.

### Follow-up review fixes

- Microsoft Teams now rejects successful HTTP responses that omit or blank the returned activity ID. Such responses raise `TeamsDeliveryError` and enter the existing delivery failure/retry path instead of being recorded as successful delivery.
- Added regression coverage for missing and whitespace-only Teams activity IDs.
- Converted the remaining supervisor-test bare assertions to the repository-required PyHamcrest assertions.

## Review disposition

- The earlier concern about exposing policy-admission rows in a second UI table was withdrawn. The documented AF-273 design intentionally keeps provider-observation and policy-admission rows in the raw Journal/API troubleshooting surface while the page shows condensed health and failure detail.
- The Teams acknowledgement issue and test-assertion standards issue were fixed in commit `948ec8b6`.

## Validation

- `make check-api` — passed.
- `git diff --check` — passed.
- `uv run pytest --confcutdir=tests/unit tests/unit/test_msteams_client.py tests/unit/test_communications_supervisor.py -q` — 22 passed.
- The preceding complete runs passed 1,613 API tests and 221 UI tests. The final full API rerun was not possible because the Docker daemon required by the repository-wide test fixture was unavailable; the final follow-up change does not touch UI code.

## Release notes

- The branch includes the required journal/error-detail migrations.
- No additional migration is required for the final Teams/test-only follow-up fix.
- No provider credentials, message bodies, or raw provider error payloads are added to the journal or diagnostics response.
