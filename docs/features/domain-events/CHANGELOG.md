# Domain Events — change log

Status: Active
Epic: [AF-218](https://aai-labs.atlassian.net/browse/AF-218) (Domain Event, transactional outbox, and delivery infrastructure)
Related context: [domain-events feature doc](../domain-events.md), [transactional outbox ADR](../../adr/2026-07-25-transactional-domain-event-outbox.md)

## Current state

- Delivered: typed Domain Event envelope, code-owned event registry with payload validation, transactional `event_outbox_message` staging, mutable `event_delivery` rows per intended handler with a `PENDING → ENQUEUED → PROCESSING → SUCCEEDED | DEAD_LETTERED` lifecycle, Dramatiq/Redis at-least-once transport behind an adapter, delivery reconciliation with configured stale thresholds, RBAC audit events (AF-219), and a Platform Administrator–only read-only Event Delivery Monitor API and Platform View page (AF-247).
- In transition: none; the monitor is strictly read-only and adds no retry/replay/delete surfaces.
- Next: remaining event/audit slices under AF-218 through AF-221; Organization-scoped or public monitoring is explicitly out of scope for AF-247.
- Blockers: none.

## Changes

### 2026-07-25 — [AF-247](https://aai-labs.atlassian.net/browse/AF-247) — PR pending — Platform Event Delivery Monitor

- Delivered: a read-only Event Delivery monitoring surface for Platform Administrators — global `/dashboard/platform/event-deliveries` Platform View page plus `GET /api/v1/platform/event-deliveries/summary`, `GET /api/v1/platform/event-deliveries`, and `GET /api/v1/platform/event-deliveries/event-types`. Endpoints are global, require no Active Organization, return `401` unauthenticated and `403` for non-Platform-Admins, and read PostgreSQL as the source of truth (no raw Redis/Dramatiq inspection).
- Changed: added Event Delivery explorer repository queries (deterministic `(created_at, id)` ordering, page/offset contract with 50/100 default/max, status/Organization/event-name/created-range filters, exact-ID and case-insensitive-prefix search, `last_error` never searched) and a global summary with per-status counts plus active-state oldest age, stale count, unknown-age count, and reconciler-sourced thresholds. Added the `b7f3d8e1c4a9_add_event_delivery_monitor_indexes` migration. UI uses TanStack `useInfiniteQuery` + TanStack Virtual with URL-backed filters/sort, one expandable row at a time, and a manual Refresh that clears pages, collapses the row, scrolls to top, and refetches (no polling).
- Documented: added the **Platform Event Delivery Monitor** section, response/redaction contract, and source-map rows to [`../domain-events.md`](../domain-events.md); safe-metadata-only responses re-apply bounded/redacted `last_error` at the read boundary and never expose Event Payload, Actor/Subject Identity, or correlation/causation data.
- Verified: API integration tests in `api/tests/integration/test_event_delivery_monitor.py` cover authorization, summary boundaries, stale/unknown ages, filters/search, pagination/order, redaction, and refresh; UI Playwright coverage in `ui/tests/e2e/event-deliveries.spec.ts` covers loading/error/empty states, filters, URL persistence, infinite loading, virtualization, expansion, and refresh.
- Corrected: the global explorer includes Platform-scoped deliveries, whose nullable organization fields are rendered as `Platform` in the UI.
- Follow-up: none for AF-247. Manual retry/replay/remapping, deletion, retention, Organization-scoped monitoring, and a general Outbox Message browser remain explicitly excluded.
