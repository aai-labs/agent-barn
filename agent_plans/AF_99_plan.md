# AF-99 — Tool Call Logging: Implementation Plan

## Context

Operators need a UI to browse the audit trail of every tool call made by an agent — read-only, paginated, filterable by tool name, status, and date range. This is a precursor to Epic 4 (full conversation + tool-call audit log) but scoped narrowly to tool calls only.

The producer side of Epic 4 (`AF-26` plugin, `AF-27` ingest endpoint) is not built yet, and we want to ship AF-99 without waiting for them. Spike confirmed that openclaw already persists every tool call to JSONL transcripts on the agent's PVC — so we can be a passive consumer of openclaw's own storage and skip building any producer infrastructure.

---

## Decisions

| Concern | Decision |
|---|---|
| Producer | None. Openclaw already writes tool calls to JSONL transcripts on each agent's PVC. No plugin, no ingest endpoint, no agent-pod outbound calls. |
| Transport from pod to awm-api | Existing `KubernetesClient.exec_command` (subprocess to `kubectl exec`). Tried switching to the in-process Python SDK but the API SA only has `create pods/exec` (SPDY POST), not `get pods/exec` (websocket GET). RBAC isn't managed in this repo. Deferred to a follow-up that adds Role + RoleBinding to the helm chart. |
| Sync trigger | Background fire-and-forget. `GET /agents/{id}/tool-calls` submits a sync task to a `ThreadPoolExecutor` (max 4 workers) and immediately returns Postgres results without waiting. Rate-limited to one sync per 4 seconds per agent (`_MIN_SYNC_INTERVAL_SECONDS`). `force=True` bypasses the rate limit — used by `stop_agent` (must flush before pod deletion) and integration tests. |
| Sync granularity | Incremental — per-(agent, session-file) byte offset stored in `tool_call_sync_state`. First sync per agent is slow (reads everything); subsequent syncs read only new bytes. |
| Sync failures | Swallowed. If the pod is unreachable or exec fails, we still serve whatever's already in Postgres. The route never 5xx's because of a sync failure. |
| Storage | Postgres `tool_call` table. JSONL data from openclaw is projected into a query-optimized row per tool call. |
| Idempotency | Unique `(agent_id, external_id)` where `external_id = openclaw toolCall.id` (e.g. `call_ppiEohyny...`). Re-syncing the same line is a no-op. |
| ToolCall ↔ ToolResult pairing | Two separate JSONL entries in openclaw. We insert tool calls in `PENDING` status from the assistant `toolCall` entry, then update to `SUCCESS`/`ERROR` when we see the matching `toolResult` entry. |
| UI polling | React Query `refetchInterval: 5_000` while tab is mounted, `false` otherwise. No WebSocket. |
| Live-feel vs read-mostly | This is a read-history UX (browse/filter/paginate past tool calls). Polling is sufficient. |
| Pruning risk | Openclaw can prune old sessions per configurable retention. Lazy sync means data not yet copied to Postgres can be lost. Accepted for v0; mitigated later via event-driven sync on `start_agent`/`stop_agent`. |
| Cross-agent search | Out of scope for v0. UI scope is "this one agent." Schema supports cross-agent queries later. |
| Conversation replay | Out of scope. AF-99 only surfaces tool calls, not the surrounding messages. AF-29 covers replay. |

---

## Branching & review

One branch (`AF-99-add-tool-call-logging`) → one PR. The work below is structured as logical phases (so each phase can be a separate commit for easier review), but they ship together.

| Phase | Commit scope | Dependencies |
|---|---|---|
| 1 | Migration + `tool_calls` models + repository | — |
| 2 | JSONL parser (pure functions + fixtures + unit tests) | — |
| 3 | Sync service + route + integration tests | 1, 2 |
| 4 | UI: schemas, hook, tool-calls tab, agent-detail-page wiring | 3 (API contract) |
| 5 | E2E tests + polish | 4 |

A SDK-exec migration was scoped originally but pulled out — it requires an RBAC change (`get pods/exec`) the helm chart doesn't currently manage. Filed as a follow-up.

---

## Data model

Openclaw writes one JSONL file per session at `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl` on the agent PVC. The schema we care about (confirmed against a live pod during the spike):

**Tool call (assistant turn):**
```json
{
  "type": "message",
  "id": "76fe59b9",
  "timestamp": "2026-05-20T11:18:37.846Z",
  "message": {
    "role": "assistant",
    "content": [{
      "type": "toolCall",
      "id": "call_ppiEohyny133JGEiW98cIbdA",
      "name": "read",
      "arguments": {"path": "...", "offset": 1, "limit": 200}
    }],
    "model": "gpt-5-mini",
    "timestamp": 1779275907575
  }
}
```

**Tool result:**
```json
{
  "type": "message",
  "id": "5e7ca740",
  "parentId": "76fe59b9",
  "timestamp": "2026-05-20T11:18:37.924Z",
  "message": {
    "role": "toolResult",
    "toolCallId": "call_ppiEohyny133JGEiW98cIbdA",
    "toolName": "read",
    "content": [{"type": "text", "text": "..."}],
    "isError": false,
    "timestamp": 1779275917924
  }
}
```

Mapping from openclaw JSONL → our `tool_call` row:

| `tool_call` column | Openclaw source |
|---|---|
| `external_id` | `content[].id` on toolCall; `message.toolCallId` on toolResult (pairing key) |
| `session_id` | filename (`<sessionId>.jsonl`) |
| `tool_name` | `content[].name` on toolCall (or `message.toolName` on toolResult) |
| `arguments` | `content[].arguments` from toolCall (JSONB) |
| `result` | `message.content` from toolResult (JSONB) — null while PENDING |
| `status` | `PENDING` until toolResult seen; then `SUCCESS` if `isError == false`, else `ERROR` |
| `occurred_at` | `message.timestamp` (unix ms) on the toolCall message |
| `completed_at` | `message.timestamp` (unix ms) on the toolResult message |
| `duration_ms` | `completed_at - occurred_at` (computed) |

---

## Architecture

### Sync flow (per `GET /agents/{id}/tool-calls` request)

```
1. ToolCallService.list_tool_calls():
   a. Submit ToolCallSyncService.sync_agent(agent_id, org_id) to a background ThreadPoolExecutor.
   b. Immediately query Postgres (filtered + paginated SELECT from tool_call WHERE agent_id = ?).
   c. Return PaginatedItems[ToolCallRead] — caller never waits for sync.

2. ToolCallSyncService.sync_agent() [background thread]:
   a. Rate-limit check: if last_synced_at < 4 s ago, skip (prevents pile-up from 5 s UI poll).
   b. Resolve pod name via KubernetesClient. If no pod, return.
   c. List session JSONL files in pod:
        find /home/node/.openclaw/agents/main/sessions -name '*.jsonl' -not -name '*.trajectory.jsonl'
   d. Dispatch one thread per file (inner ThreadPoolExecutor, max 8 workers):
        For each file:
          i.  Look up tool_call_sync_state; get byte offset (default 0).
          ii. Exec: tail -c +<offset+1> <file>   (reads new bytes only).
          iii. Parse lines (toolCall → upsert PENDING; toolResult → UPDATE to SUCCESS/ERROR).
          iv. In one DB transaction: flush tool_call rows + advance sync offset. COMMIT.
   e. If sync raises at any level, log warning and swallow — never propagates to the HTTP response.

3. AgentService.stop_agent() [forced sync]:
   a. Calls sync_agent(agent_id, org_id, force=True) synchronously before deleting the deployment.
   b. force=True bypasses the rate-limit check so the final flush always runs.
```

### Domain layout (matches existing pattern)

```
api/domains/tool_calls/
  __init__.py
  models.py        — DB models, enums, Pydantic request/response schemas, filter dependency
  repository.py    — query layer (filters, pagination, sync state, get_most_recent_sync_time)
  service.py       — background sync submission + Postgres query (routes call this only)
  sync_service.py  — orchestrates kubectl exec, JSONL parsing, DB writes, rate limiting
  routes.py        — FastAPI handler (one GET endpoint; imports AgentService + ToolCallService only)
  jsonl_parser.py  — pure functions: parse openclaw JSONL → ToolCall rows
```

**Architecture constraint**: routes may only import services. Cross-module imports must only be services — never repositories, models, or other internals from another domain.

### `KubernetesClient`

No change. `exec_command` continues to use `subprocess.run(["kubectl", ...])`. A follow-up ticket will move both the helm chart's RBAC and the implementation to use the in-process SDK (requires granting `get pods/exec` to the API SA via a new Role/RoleBinding).

---

## Files Changed

### API

| File | Change |
|---|---|
| `api/domains/tool_calls/__init__.py` | New — package marker. |
| `api/domains/tool_calls/models.py` | New — `ToolCallStatus` enum; `ToolCall` and `ToolCallSyncState` table models; `ToolCallRead`, `ToolCallFilter`, `get_tool_call_filter` dependency. |
| `api/domains/tool_calls/repository.py` | New — `find_by_agent(agent_id, filter, pagination)`, `get_sync_state(agent_id, file_path)`, `upsert_pending(rows)`, `complete(external_id, ...)`, `save_sync_state(...)`. |
| `api/domains/tool_calls/parser.py` | New — pure functions: `iter_entries(text) -> Iterable[dict]`, `parse_tool_call(entry) -> ToolCallPending`, `parse_tool_result(entry) -> ToolCallCompletion`. No I/O. |
| `api/domains/tool_calls/service.py` | New — `ToolCallService` with `sync(agent)` (best-effort) and `list(agent_id, filter, pagination, context)`. |
| `api/domains/tool_calls/routes.py` | New — `tool_calls_router` with prefix `/agents/{agent_id}/tool-calls`; one GET handler. |
| `api/migrations/versions/f0c9d4a5e1b2_add_tool_call_tables.py` | New — creates `toolcallstatus` enum, `tool_call` table with indexes, `tool_call_sync_state` table. |
| `api/migrations/env.py` | Import `api.domains.tool_calls.models` so Alembic discovers the tables. |
| `api/api_app.py` | Register `tool_calls_router` on the sub-api. |
| `api/tests/steps/tool_call.py` | New — `there_is_a_tool_call(agent, name, status, ...)` step seeder; `MOCK_SESSION_JSONL` fixture with realistic JSONL excerpts. |
| `api/tests/integration/test_tool_calls.py` | New — integration tests for list endpoint (filters, pagination, auth, org scoping) and sync behavior (mocked `KubernetesClient.exec_command`). |

### UI

| File | Change |
|---|---|
| `ui/src/features/tool-calls/schemas.ts` | New — Zod schemas: `ToolCallSchema`, `PaginatedToolCallsSchema`. |
| `ui/src/features/tool-calls/utils.ts` | New — `toolCallsKey` query key structure, `TOOL_CALLS_PAGE_SIZE`. |
| `ui/src/features/tool-calls/hooks/use-tool-calls.ts` | New — `useToolCalls(agentId, filters, page)` with `refetchInterval: 5_000` while mounted. |
| `ui/src/features/tool-calls/components/tool-calls-tab.tsx` | New — table view + filter bar (tool name input, status select, date range) + pagination + collapsible argument/result panels. |
| `ui/src/features/agents/components/agent-detail-page.tsx` | Add "Tool calls" tab to the tab list; render `<ToolCallsTab agent={agent} />`. |
| `ui/tests/pages/data-support/tool-call-data-support.po.ts` | New — `interceptGetToolCallsRequest` Playwright route mock. |
| `ui/tests/pages/data-support/data-support.po.ts` | Add `toolCalls: ToolCallDataSupport` property. |
| `ui/tests/pages/agent-detail-page.po.ts` | Add `toolCallsTab()` locator. |
| `ui/tests/e2e/tool-calls-tab.spec.ts` | New — E2E: tab navigation, rows render, filter by tool name, filter by status, pagination, error state. |

---

## Implementation details

### `tool_call` schema

```python
class ToolCallStatus(str, enum.Enum):
    PENDING = "PENDING"  # toolCall seen, toolResult not yet
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"

class ToolCall(BaseModel, table=True):
    __tablename__ = "tool_call"
    __table_args__ = (
        Index("ix_tool_call_agent_occurred", "agent_id", "occurred_at"),
        Index("ix_tool_call_agent_tool", "agent_id", "tool_name"),
        UniqueConstraint("agent_id", "external_id", name="uq_tool_call_agent_external"),
    )

    organization_id: UUID  # FK, for query scoping
    agent_id: UUID         # FK to agent
    session_id: str        # openclaw session UUID (string)
    external_id: str       # openclaw toolCall id, e.g. "call_ppiEohyny..."
    tool_name: str
    arguments: dict        # JSONB
    result: dict | None    # JSONB; null while PENDING
    status: ToolCallStatus
    occurred_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
```

### `tool_call_sync_state` schema

```python
class ToolCallSyncState(BaseModel, table=True):
    __tablename__ = "tool_call_sync_state"
    __table_args__ = (
        UniqueConstraint("agent_id", "session_file_path", name="uq_tcss_agent_file"),
    )

    agent_id: UUID
    session_file_path: str  # absolute path inside pod, e.g. "/home/node/.openclaw/agents/main/sessions/<id>.jsonl"
    last_byte_offset: int   # # bytes of the file already consumed
    last_synced_at: datetime
```

### Filter and route

```
GET /api/v1/agents/{agent_id}/tool-calls
  ?page=1
  &page_size=20
  &tool_name=<substring>     # ILIKE
  &status=PENDING|SUCCESS|ERROR
  &from_date=<ISO datetime>  # occurred_at >=
  &to_date=<ISO datetime>    # occurred_at <
```

Returns `PaginatedItems[ToolCallRead]`.

### Parser correctness notes

- Skip entries where `type != "message"`.
- Tool call: `entry.message.role == "assistant"` AND any `content[].type == "toolCall"`. An assistant turn can contain multiple tool calls; we treat each as a separate row.
- Tool result: `entry.message.role == "toolResult"`. Use `message.toolCallId` to find the matching row.
- If a toolResult arrives for a toolCall we haven't seen yet (would only happen with manual file edits or partial sync), we log and skip — re-sync will pick it up on the next pass.
- The `arguments` and `result` objects can be arbitrary openclaw payloads; stored as-is in JSONB.

### Ingestion tracking — two complementary mechanisms

We use **two** tables to track what we've ingested. One for efficiency, one for safety.

| Mechanism | Table | What it gives us |
|---|---|---|
| Byte offset per session file | `tool_call_sync_state` | **Efficiency** — never re-transfer or re-parse bytes we've already seen |
| Unique constraint per tool call id | `tool_call` (`UNIQUE (agent_id, external_id)`) | **Correctness** — re-ingesting the same data is always a no-op |

Byte offset is the optimistic path. The unique constraint is the pessimistic safety net. Either alone would work, but together they make sync both fast *and* robust against any kind of failure or replay.

### Sync incremental algorithm

For each session file currently in the pod:

```python
offset = repo.get_sync_offset(agent_id, file_path)  # 0 if no row
tail_output = exec_command(pod, ns, ["sh", "-c", f"tail -c +{offset + 1} {file_path}"])
new_bytes = len(tail_output.encode("utf-8"))
if new_bytes == 0:
    continue  # nothing new in this file

# Inside one DB transaction:
for line in tail_output.splitlines():
    entry = json.loads(line)
    if is_tool_call(entry):
        repo.insert_pending(...)  # INSERT ... ON CONFLICT DO NOTHING
    elif is_tool_result(entry):
        repo.complete(external_id=entry.toolCallId, ...)  # UPDATE WHERE external_id=?

repo.save_sync_offset(agent_id, file_path, offset + new_bytes)
# COMMIT
```

Since openclaw transcripts are append-only within a session, the file only grows. `tail -c +N` reads from byte N onward — so we transfer exactly the new bytes, not the whole file.

A new session shows up as a new file → no `tool_call_sync_state` row → starts from offset 0 → full read of that (typically small) file. Files we've already drained: offset is at EOF, `tail` returns empty, no work done.

### Transaction boundary

Each file's sync is one DB transaction: insert/update tool_call rows **and** advance the sync offset together. If anything inside fails, the transaction rolls back — the offset stays where it was, and the next sync redoes the work. Combined with `ON CONFLICT DO NOTHING`, redoing the work is always safe (no duplicates).

### Edge cases handled by this design

| Scenario | Outcome |
|---|---|
| Sync runs while openclaw is appending | We read up to `tail`'s snapshot, advance offset to that point. Next sync picks up the rest. |
| ToolCall arrives this sync, toolResult in next sync | First sync inserts a `PENDING` row. Second sync's `UPDATE WHERE external_id=?` matches it and fills in result + status + completed_at. |
| Re-running sync manually | Every insert hits `ON CONFLICT DO NOTHING`. Every update is idempotent. Offset advances at most to current EOF. Safe and ~free if nothing changed. |
| Sync crashes mid-write | Transaction rolls back. Offset stays. Next sync redoes the work. `ON CONFLICT` keeps it correct. |
| Openclaw prunes a session file | File disappears from `find` output → not iterated. Existing `tool_call` rows in our DB stay; the stale `tool_call_sync_state` row is harmless (we can clean up unreferenced rows in a follow-up). |
| Same toolCall id across two agents (shouldn't happen but) | Unique constraint is `(agent_id, external_id)`, not just `external_id`. Each agent has its own namespace. |
| File shrinks/truncates (not expected in v0 — openclaw transcripts are append-only) | `tail -c +N` returns empty when N > file size. v0 leaves offset as-is; if this ever becomes a real case, follow-up: detect via `stat` and reset offset to 0. |

### What "what have we ingested?" looks like in the DB

- **Which byte ranges of which files have we read?** → `SELECT * FROM tool_call_sync_state WHERE agent_id = ?`
- **Which individual tool calls have we recorded?** → `SELECT external_id FROM tool_call WHERE agent_id = ?`

### UI states to render

1. **No tool calls yet** — empty state with copy "No tool calls recorded yet."
2. **Loading** — skeleton table rows.
3. **Sync failed but stale data exists** — render the table; show a subtle warning banner ("Live data unavailable; showing last known").
4. **Filter results empty** — "No tool calls match these filters."
5. **Error fetching from API** — `AppErrorState` with retry.

### React Query polling

```ts
useQuery({
  queryKey: toolCallsKey.list({ agentId, ...filters, page }),
  queryFn: ...,
  refetchInterval: 5_000,
  refetchOnWindowFocus: true,
  placeholderData: keepPreviousData,
});
```

`refetchInterval` is paused when the component unmounts (so tabbing away from "Tool calls" stops polling). React Query also pauses interval refetches when the document is hidden.

---

## Testing

### API unit tests

- Parser: feed real JSONL excerpts captured from the spike pod (saved as test fixtures), assert correct extraction.
- Parser: tool calls without matching results stay PENDING.
- Parser: malformed lines are skipped, not raised.

### API integration tests

`MockK8sModule` returns canned JSONL via `exec_command`. Cover:

- Sync inserts new tool calls; idempotent on re-run.
- Sync transitions PENDING → SUCCESS/ERROR when toolResult appears.
- Sync state byte offset advances correctly across multiple sync calls.
- Sync swallows exec failures; endpoint still returns rows already in DB.
- Filters: `tool_name`, `status`, `from_date`, `to_date` each work and combine.
- Pagination: `page` and `page_size` honored, `total` accurate.
- Org scoping: tool calls for an agent in org A are invisible to a user in org B.
- Soft-deleted agent: 404.
- No auth: 401.

### UI E2E tests

Mock `GET /api/v1/agents/{id}/tool-calls` via Playwright route. Cover:

- Tab navigation displays the panel.
- Rows render: timestamp formatted, tool name, status badge, duration.
- Tool name filter updates query string and refetches.
- Status filter works.
- Pagination next/prev work.
- Error state displays retry.
- Empty state copy renders when 0 results.

---

## Out of scope (deferred to follow-ups)

- Cron / scheduled background sync. The current background sync is per-request and rate-limited; it does not run while the UI is closed.
- Sync on `start_agent`. Deferred; `stop_agent` already forces a final sync before pod deletion.
- Cross-agent / fleet-wide tool-call search.
- Conversation replay (covered by AF-29).
- WebSocket streaming.
- Real-time live tool-call feed (different UX from audit log).
- Migration to push-based ingest endpoint (AF-26/AF-27). Schema is shaped so a future ingest endpoint can write the same rows.

---

## Deployment checklist

- [ ] Run migration: `kubectl exec -n agent-farm deploy/agentfarm-api -- python -m alembic upgrade head`
- [ ] Confirm API ServiceAccount has `create` on `pods/exec` (already granted for `pair_agent`).
- [ ] No new env vars required.
- [ ] No new k8s resources required.
- [ ] Smoke test: open Tool calls tab on a RUNNING agent that has done at least one tool call → rows appear; filter by tool name → list narrows; refresh → poll-driven updates appear within 5s of new activity.
