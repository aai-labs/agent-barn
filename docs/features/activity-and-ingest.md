# Activity and Ingest

## Read when

Read before changing conversation history, channel/thread grouping, runtime message parsers, tool-call audit records, telemetry authentication, idempotency, or the Activity UI.

## Role in the system

The separately served Ingest API receives authenticated runtime telemetry. It persists Conversation Messages and Tool Calls, which the organization-scoped product API exposes as agent activity. These runtime Telemetry Events are separate from internal Domain Events and are not written to the Domain Event outbox.

## Invariants

- Ingest authenticates with agent ID plus the stored per-agent ingest key generated at start. Authentication checks identity and key, not AgentStatus; stop does not currently clear the key.
- Message identity is unique per `(agent_id, openclaw_msg_id)` for both runtimes.
- Hermes-generated external message IDs use a `hermes:` prefix, despite the persisted field's OpenClaw-specific name.
- Conversation messages record direction, channel/direct-message type, session, channel, optional thread, names, content, and occurrence time.
- Outbound telemetry is attributed to the chat that produced it through the runtime's own session correlation — Hermes resolves the completed call's `session_id` against the gateway session store, OpenClaw correlates `agent_end` to the inbound message by session key. Telemetry that cannot be attributed is dropped at the runtime plugin with a warning rather than recorded against another chat.
- Tool results are paired to their call by the runtime's per-invocation call id, so concurrent calls to one tool within a task stay distinct.
- Tool calls are unique per `(agent_id, external_id)` and use `PENDING`, `SUCCESS`, or `ERROR` status.
- Duplicate message and pending tool-call identities are handled idempotently. Tool results update any matching row regardless of its current status; a result arriving before its pending event is currently dropped.
- Product API conversation and tool-call reads require `activity.read` and are scoped through an accessible, organization-owned, non-deleted Agent. Assigned Members cannot bypass Agent Access through activity endpoints.
- Runtime Ingest writes use Agent identity plus ingest-key authentication rather than a human Membership or Agent Access check.
- Telemetry Events are runtime-originated operational facts. They are not Domain Events, Outbox Messages, Event Deliveries, or Security Audit Records.
- Slack channel and sender names may be enriched best-effort; Telegram chat names are cached with a 10-minute TTL. Teams activity has no equivalent directory enrichment in this domain.

## Data flow

```text
OpenClaw/Hermes runtime
        ↓ agent ID + ingest key
Ingest service
   ├── message upsert → Conversation repository
   └── tool pending/result upsert → Tool Call repository
        ↓
Conversation and Tool Call APIs
        ↓
Agent Activity UI
```

Conversation reads list channels and return cursor-paginated messages or grouped threads. Tool-call reads support tool, status, and date filters with pagination.

## Boundaries

Runtime parsers own translation from runtime-specific records into the shared ingest contract. Ingest owns authentication and write orchestration. Conversation and Tool Call domains own read models and query behavior. Costs do not derive from these activity records.

## Source map

| Concern                                        | Authoritative source                                                                                                                                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Ingest app and process entry                   | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                                                                                                                                                                |
| Ingest contracts and authentication/write flow | `../../api/domains/ingest/models.py`, `../../api/domains/ingest/service.py`, `../../api/domains/ingest/routes.py`                                                                                                                          |
| Conversation persistence and read API          | `../../api/domains/conversations/`                                                                                                                                                                                             |
| Hermes parsing                                 | `../../api/domains/conversations/hermes_parser.py`                                                                                                                                                                             |
| Shared/runtime parsing                         | `../../api/domains/conversations/parser.py`                                                                                                                                                                                    |
| Tool-call state and query API                  | `../../api/domains/tool_calls/`                                                                                                                                                                                                |
| Runtime telemetry configuration                | `../../api/domains/agents/service.py`, runtime builders/base configs                                                                                                                                                           |
| UI activity hooks and tabs                     | `../../ui/src/features/agents/hooks/use-conversations.ts`, `../../ui/src/features/agents/hooks/use-tool-calls.ts`, `../../ui/src/features/agents/components/conversations-tab.tsx`, `../../ui/src/features/agents/components/tool-calls-tab.tsx` |
| Tests                                          | `../../api/tests/integration/test_ingest.py`, `../../api/tests/integration/test_conversations.py`, `../../api/tests/integration/test_tool_calls.py`, related unit parser/repository tests                                                  |
| Runtime plugin tests                           | `../../api/tests/unit/test_hermes_telemetry_push_plugin.py`, `../../api/tests/unit/test_openclaw_telemetry_push_plugin.py`, harness in `../../api/tests/helpers/telemetry_plugins.py`                                                      |
| Runtime contract checks                        | `../../hermes-base/smoke-test.sh`, `../../openclaw-base/smoke-test.sh`, and the plugin-contract step in `../../.github/workflows/hermes-base.yml`                                                                                          |

## Related decisions

- [`2026-07-17-push-based-runtime-telemetry.md`](../adr/2026-07-17-push-based-runtime-telemetry.md)
- Domain Event boundaries are documented separately in [`domain-events.md`](domain-events.md).

## Change impact

Telemetry contract changes require both runtime producers, ingest DTOs/services, parser tests, repositories, read API schemas, UI Zod schemas/hooks, and activity tests. Identity or idempotency changes require migration and duplicate-delivery coverage.
