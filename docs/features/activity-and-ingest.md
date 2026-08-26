# Activity and Ingest

## Read when

Read before changing conversation history, Connection/channel/thread grouping, Communication Delivery ingestion, tool-call audit records, telemetry authentication, idempotency, or the Activity UI.

## Role in the system

Conversation Messages and Tool Calls share the Agent Activity UI but have different write boundaries. The Communications Gateway persists canonical Conversation Messages from provider ingress and runtime replies. The separately served Ingest API persists authenticated runtime Tool Call telemetry. Neither path writes Domain Events to the Domain Event outbox.

## Invariants

- Ingest authenticates with agent ID plus the stored per-agent ingest key generated at start. Authentication checks identity and key, not AgentStatus; stop does not currently clear the key.
- Message identity is unique per `(connection_id, provider_message_id)`; the legacy `openclaw_msg_id` column stores that provider identity for all Platforms.
- Conversation location identity is `(connection_id, channel_id)`. Read DTOs, repository filters, API paths, UI query keys, and URL selection preserve both values so same-platform Connections may safely reuse provider channel identifiers.
- Conversation Messages record their source Connection, direction, channel/direct-message type, session, location, optional thread, names, content, and occurrence time.
- Runtime replies are bound to their source Communication Delivery, which supplies the originating Connection and location; the runtime cannot redirect a reply to another Connection.
- Tool results are paired to their call by the runtime's per-invocation call id, so concurrent calls to one tool within a task stay distinct.
- Tool calls are unique per `(agent_id, external_id)` and use `PENDING`, `SUCCESS`, or `ERROR` status.
- Duplicate message and pending tool-call identities are handled idempotently. Tool results update any matching row regardless of its current status; a result arriving before its pending event is currently dropped.
- Product API conversation and tool-call reads require `activity.read` and are scoped through an accessible, organization-owned, non-deleted Agent. Assigned Members cannot bypass Agent Access through activity endpoints.
- Runtime Ingest Tool Call writes use Agent identity plus ingest-key authentication rather than a human Membership or Agent Access check. Runtime communication claims/replies use a separate versioned Communications protocol credential.
- Telemetry Events are runtime-originated operational facts. They are not Domain Events, Outbox Messages, Event Deliveries, or Security Audit Records.
- Platform Plugins normalize provider-specific identities into the canonical envelope. Missing sender/location display names are resolved by an optional, best-effort `enrich_inbound` plugin seam that the Communications Gateway invokes centrally — for supervised ingress, driver events, and webhook events alike — after admission and before persistence. Enrichment lookups are cached, credential-scoped, and never delay or reject durable message acceptance on failure.

## Data flow

```text
Platform provider → Platform Plugin → Communication Delivery/Conversation repository
Agent runtime ─────→ Communications protocol ────────┘
Agent runtime ─────→ Ingest API → Tool Call repository
                                      ↓
                         Conversation and Tool Call APIs
                                      ↓
                              Agent Activity UI
```

Conversation reads list channels and return cursor-paginated messages or grouped threads. Tool-call reads support tool, status, and date filters with pagination.

## Boundaries

Platform Plugins own translation from provider payloads into the normalized communication envelope. Communications owns durable message/reply orchestration. Ingest owns Tool Call telemetry authentication and writes. Conversation and Tool Call domains own read models and query behavior. Costs do not derive from these activity records.

## Source map

| Concern                                        | Authoritative source                                                                                                                                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Ingest app and process entry                   | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                                                                                                                                                                |
| Ingest Tool Call authentication/write flow     | `../../api/domains/ingest/service.py`, `../../api/domains/ingest/routes.py`                                                                                                                          |
| Communications app and delivery flow           | `../../api/communications_app.py`, `../../api/domains/communications/`                                                                                                                                |
| Conversation persistence and read API          | `../../api/domains/conversations/`                                                                                                                                                                                             |
| Provider normalization                         | `../../api/domains/communications/plugins/`                                                                                                                                                                                    |
| Tool-call state and query API                  | `../../api/domains/tool_calls/`                                                                                                                                                                                                |
| Runtime protocol configuration                 | `../../api/domains/agents/service.py`, runtime builders, `../../api/domains/agents/scripts/communications-runtime-adapter.py`                                                                                                  |
| UI activity hooks and tabs                     | `../../ui/src/features/agents/hooks/use-conversations.ts`, `../../ui/src/features/agents/hooks/use-tool-calls.ts`, `../../ui/src/features/agents/components/conversations-tab.tsx`, `../../ui/src/features/agents/components/tool-calls-tab.tsx` |
| Tests                                          | `../../api/tests/integration/test_ingest.py`, `../../api/tests/integration/test_conversations.py`, `../../api/tests/integration/test_tool_calls.py`, related unit parser/repository tests                                                  |
| Platform Plugin tests                          | `../../api/tests/unit/test_communications_plugins.py`, `../../api/tests/integration/test_communication_deliveries.py`                                                                                                           |

## Related decisions

- [`2026-07-17-push-based-runtime-telemetry.md`](../adr/2026-07-17-push-based-runtime-telemetry.md)
- Domain Event boundaries are documented separately in [`domain-events.md`](domain-events.md).

## Change impact

Conversation contract changes require normalized envelopes, Communication Delivery persistence, read API schemas, UI Zod schemas/hooks, and Connection-isolation tests. Tool Call telemetry changes require both runtime producers, Ingest services, repositories, and Activity UI coverage. Identity or idempotency changes require migration and duplicate-delivery coverage.
