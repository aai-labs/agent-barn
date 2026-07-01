# Plan: Show Agent Pod Logs in UI

## Context

Agents are deployed as Kubernetes pods. There is no way to view their stdout/stderr logs from the UI today. This feature adds a **Logs** tab to the agent detail page that:

1. Fetches the last 100 lines on initial load (from live pod or DB snapshot)
2. Streams new lines in real-time via SSE while the agent is running
3. Lets the user scroll up to load earlier logs (current session, then previous sessions)
4. Persists logs to the database before stopping an agent so they survive stop/start cycles

The "Work" tab remains untouched (reserved for future activity/spend data).

---

## Sub-Task 1: K8s Client — Add Log Methods

**Files:** `api/infrastructure/kubernetes/client.py`

**Tests first** in `api/tests/unit/test_kubernetes_client.py`:
- `test_read_pod_logs_returns_text_when_pod_exists`
- `test_read_pod_logs_returns_none_when_no_pod`
- `test_read_pod_logs_returns_none_on_404`
- `test_stream_pod_logs_yields_lines`
- `test_stream_pod_logs_returns_empty_when_no_pod`

**Then implement** two new methods on `KubernetesClient`:

```python
def read_pod_logs(
    self,
    deployment_name: str,
    namespace: str,
    tail_lines: int = 100,
    container: str = "agent",
) -> str | None:
    pod_name = self.get_pod_name_for_deployment(deployment_name, namespace)
    if pod_name is None:
        return None
    try:
        return self._core_v1.read_namespaced_pod_log(
            pod_name,
            namespace,
            container=container,
            tail_lines=tail_lines,
            timestamps=False,
        )
    except ApiException as e:
        if e.status == 404:
            return None
        raise

def stream_pod_logs(
    self,
    deployment_name: str,
    namespace: str,
    tail_lines: int = 0,
    container: str = "agent",
) -> Generator[str, None, None]:
    pod_name = self.get_pod_name_for_deployment(deployment_name, namespace)
    if pod_name is None:
        return
    resp = self._core_v1.read_namespaced_pod_log(
        pod_name,
        namespace,
        container=container,
        tail_lines=tail_lines,
        follow=True,
        _preload_content=False,
    )
    try:
        for raw_line in resp:
            yield raw_line.decode("utf-8", errors="replace").rstrip("\n")
    finally:
        resp.close()
        resp.release_conn()
```

Add `from collections.abc import Generator` to imports.

---

## Sub-Task 2: DB Model + Migration

**File:** `api/domains/agents/models.py`

Add `AgentLogSnapshot` table model after the existing `AgentSkill` model:

```python
class AgentLogSnapshot(BaseModel, table=True):
    __tablename__: str = "agent_log_snapshot"

    __table_args__ = (
        Index(
            "ix_agent_log_snapshot_agent_ended",
            "agent_id",
            sa.text("session_ended_at DESC"),
        ),
    )

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    session_started_at: datetime = SqlField(
        nullable=False, sa_type=sa.DateTime(timezone=True),
    )
    session_ended_at: datetime = SqlField(
        nullable=False, sa_type=sa.DateTime(timezone=True),
    )
    log_text: str = SqlField(sa_column=Column(sa.Text(), nullable=False))
    byte_size: int = SqlField(nullable=False)
```

Add `Column` to the `from sqlmodel import ...` line if not already there.

Add response models:

```python
class AgentLogsRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    lines: list[str]
    source: str  # "live" | "snapshot"
    snapshot_id: UUID | None = None
    session_started_at: datetime | None = None
    session_ended_at: datetime | None = None


class AgentLogSnapshotRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    session_started_at: datetime
    session_ended_at: datetime
    log_text: str
    byte_size: int
    created_at: datetime
```

**Migration:** Run `make makemigrations` to auto-generate the Alembic migration, then `make migrate` to apply.

---

## Sub-Task 3: Repository — Log Snapshot CRUD

**Tests first** in `api/tests/unit/test_agent_logs.py`:
- `test_save_log_snapshot_persists`
- `test_get_latest_log_snapshot_returns_most_recent`
- `test_get_latest_log_snapshot_returns_none_when_empty`
- `test_get_log_snapshots_paginated_by_cursor`

**File:** `api/domains/agents/repository.py`

Add to imports: `AgentLogSnapshot` from models.

Add methods to `AgentRepository`:

```python
def save_log_snapshot(self, snapshot: AgentLogSnapshot) -> AgentLogSnapshot:
    self.delegate.save(snapshot)
    return snapshot

def get_latest_log_snapshot(self, agent_id: UUID) -> AgentLogSnapshot | None:
    with Session(self.delegate.engine) as session:
        query = (
            select(AgentLogSnapshot)
            .where(col(AgentLogSnapshot.agent_id) == agent_id)
            .order_by(col(AgentLogSnapshot.session_ended_at).desc())
            .limit(1)
        )
        return session.exec(query).first()

def get_log_snapshots(
    self,
    agent_id: UUID,
    before_id: UUID | None = None,
    limit: int = 5,
) -> list[AgentLogSnapshot]:
    with Session(self.delegate.engine) as session:
        query = select(AgentLogSnapshot).where(
            col(AgentLogSnapshot.agent_id) == agent_id
        )
        if before_id is not None:
            pivot = session.get(AgentLogSnapshot, before_id)
            if pivot:
                query = query.where(
                    col(AgentLogSnapshot.session_ended_at) < pivot.session_ended_at
                )
        query = (
            query.order_by(col(AgentLogSnapshot.session_ended_at).desc())
            .limit(limit)
        )
        return list(session.exec(query).all())
```

---

## Sub-Task 4: Service — Log Methods + Modify stop_agent

**Tests first** in `api/tests/unit/test_agent_logs.py` (extend):
- `test_get_agent_logs_returns_live_lines_when_running`
- `test_get_agent_logs_returns_snapshot_lines_when_stopped`
- `test_get_agent_logs_returns_empty_when_no_snapshot`
- `test_capture_logs_stores_snapshot`
- `test_capture_logs_truncates_over_1mb`
- `test_capture_logs_swallows_exceptions`

**File:** `api/domains/agents/service.py`

Add imports at top:

```python
from api.domains.agents.models import (
    # ...existing imports...
    AgentLogSnapshot,
    AgentLogsRead,
    AgentLogSnapshotRead,
)
```

Add constant:

```python
_MAX_LOG_SNAPSHOT_BYTES = 1_048_576  # 1 MB
```

Add methods to `AgentService`:

```python
def get_agent_logs(
    self,
    agent_id: UUID,
    context: CurrentUserContext,
    tail_lines: int = 100,
) -> AgentLogsRead:
    org_id = self._org_id(context)
    agent = self._get_active_or_404(agent_id, org_id)

    if agent.status == AgentStatus.RUNNING:
        log_text = self.k8s.read_pod_logs(
            f"agent-{agent.id}", self.config.k8s_namespace, tail_lines=tail_lines,
        )
        lines = log_text.splitlines() if log_text else []
        return AgentLogsRead(lines=lines, source="live")

    snapshot = self.repository.get_latest_log_snapshot(agent_id)
    if snapshot is None:
        return AgentLogsRead(lines=[], source="snapshot")
    all_lines = snapshot.log_text.splitlines()
    lines = all_lines[-tail_lines:]
    return AgentLogsRead(
        lines=lines,
        source="snapshot",
        snapshot_id=snapshot.id,
        session_started_at=snapshot.session_started_at,
        session_ended_at=snapshot.session_ended_at,
    )

def stream_agent_logs(
    self,
    agent_id: UUID,
    context: CurrentUserContext,
    tail_lines: int = 0,
) -> Generator[str, None, None]:
    org_id = self._org_id(context)
    agent = self._get_active_or_404(agent_id, org_id)
    if agent.status != AgentStatus.RUNNING:
        return
    yield from self.k8s.stream_pod_logs(
        f"agent-{agent.id}", self.config.k8s_namespace, tail_lines=tail_lines,
    )

def get_log_snapshots(
    self,
    agent_id: UUID,
    context: CurrentUserContext,
    before_id: UUID | None = None,
    limit: int = 5,
) -> list[AgentLogSnapshotRead]:
    org_id = self._org_id(context)
    self._get_active_or_404(agent_id, org_id)
    snapshots = self.repository.get_log_snapshots(agent_id, before_id, limit)
    return [AgentLogSnapshotRead.model_validate(s) for s in snapshots]

def _capture_logs_before_stop(self, agent: Agent) -> None:
    try:
        log_text = self.k8s.read_pod_logs(
            f"agent-{agent.id}",
            self.config.k8s_namespace,
            tail_lines=50_000,
        )
        if not log_text:
            return
        encoded = log_text.encode("utf-8")
        if len(encoded) > _MAX_LOG_SNAPSHOT_BYTES:
            truncated = encoded[-_MAX_LOG_SNAPSHOT_BYTES:]
            log_text = truncated.decode("utf-8", errors="replace")
            idx = log_text.find("\n")
            if idx > 0:
                log_text = log_text[idx + 1 :]
        now = dt.datetime.now(dt.timezone.utc)
        self.repository.save_log_snapshot(
            AgentLogSnapshot(
                agent_id=agent.id,
                session_started_at=agent.updated_at,
                session_ended_at=now,
                log_text=log_text,
                byte_size=len(log_text.encode("utf-8")),
            )
        )
    except Exception:
        logger.warning(
            "Failed to capture logs before stop for agent %s",
            agent.id,
            exc_info=True,
        )
```

Add `from collections.abc import Generator` to imports.

**Modify `stop_agent`** — insert one line before `self.k8s.delete_deployment(...)`:

```python
self._capture_logs_before_stop(agent)
```

The full insertion point (around line 1032):

```python
        # ...existing sync block code...

        self._capture_logs_before_stop(agent)                          # NEW
        self.k8s.delete_deployment(f"agent-{agent.id}", self.config.k8s_namespace)
```

---

## Sub-Task 5: Routes — REST + SSE Endpoints

**Tests first** in `api/tests/integration/test_agent_logs.py`:
- `test_get_agent_logs_requires_auth` → 401
- `test_get_agent_logs_returns_404_for_nonexistent_agent`
- `test_get_agent_log_snapshots_returns_empty_for_new_agent`
- `test_stream_agent_logs_requires_auth` → 401

**File:** `api/domains/agents/routes.py`

Add imports at top:

```python
from fastapi.responses import StreamingResponse
from api.domains.agents.models import AgentLogsRead, AgentLogSnapshotRead
```

Add three routes. **Order matters** — put these BEFORE the `/{agent_id}` GET route to avoid FastAPI treating "logs" as a UUID path param. Insert them after the `/models` GET route:

```python
@agents_router.get("/{agent_id}/logs/stream")
def stream_agent_logs(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    tail_lines: Annotated[int, Query(ge=0, le=1000)] = 0,
):
    def event_generator():
        for line in service.stream_agent_logs(agent_id, context, tail_lines=tail_lines):
            yield f"data: {line}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@agents_router.get(
    "/{agent_id}/logs/snapshots",
    response_model=list[AgentLogSnapshotRead],
)
def get_agent_log_snapshots(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    before_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
):
    return service.get_log_snapshots(agent_id, context, before_id=before_id, limit=limit)


@agents_router.get("/{agent_id}/logs", response_model=AgentLogsRead)
def get_agent_logs(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    tail_lines: Annotated[int, Query(ge=1, le=10000)] = 100,
):
    return service.get_agent_logs(agent_id, context, tail_lines=tail_lines)
```

Route ordering: `/logs/stream`, `/logs/snapshots`, then `/logs` — ensures FastAPI doesn't treat "stream" or "snapshots" as a path parameter.

Note: These routes are under `/{agent_id}/...` which comes after `/{agent_id}` in the router. FastAPI resolves by prefix match, and since `/logs` is a fixed sub-path after `{agent_id}`, there's no ambiguity with the existing `GET /{agent_id}` route.

---

## Sub-Task 6: UI — Schemas + Query Keys

**File:** `ui/src/features/agents/schemas.ts`

Add at end, before the type exports block:

```typescript
export const AgentLogsReadSchema = z.object({
  lines: z.array(z.string()),
  source: z.enum(["live", "snapshot"]),
  snapshotId: z.string().uuid().nullable().optional(),
  sessionStartedAt: z.string().nullable().optional(),
  sessionEndedAt: z.string().nullable().optional(),
});

export const AgentLogSnapshotReadSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  sessionStartedAt: z.string(),
  sessionEndedAt: z.string(),
  logText: z.string(),
  byteSize: z.number().int(),
  createdAt: z.string(),
});
```

Add to the type exports:

```typescript
export type AgentLogsRead = z.infer<typeof AgentLogsReadSchema>;
export type AgentLogSnapshotRead = z.infer<typeof AgentLogSnapshotReadSchema>;
```

**File:** `ui/src/features/agents/utils.ts`

Add to the `agentsKey` object:

```typescript
logs: (id: string) => [..._agentsKeyBase.detail(id), "logs"] as const,
logSnapshots: (id: string) => [..._agentsKeyBase.detail(id), "log-snapshots"] as const,
```

---

## Sub-Task 7: UI — useAgentLogs Hook (initial fetch)

**File:** New `ui/src/features/agents/hooks/use-agent-logs.ts`

```typescript
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import type { AgentLogsRead } from "../schemas";
import { AgentLogsReadSchema } from "../schemas";
import { agentsKey } from "../utils";

export function useAgentLogs(agentId: string, enabled: boolean = true) {
  const query = useQuery({
    queryKey: agentsKey.logs(agentId),
    queryFn: () =>
      api
        .get<AgentLogsRead>(`/api/v1/agents/${agentId}/logs`, {
          schema: AgentLogsReadSchema,
        })
        .then((r) => r.data),
    enabled: !!agentId && enabled,
    refetchOnWindowFocus: false,
  });

  return {
    logs: query.data ?? null,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}
```

---

## Sub-Task 8: UI — useAgentLogStream Hook (SSE)

**File:** New `ui/src/features/agents/hooks/use-agent-log-stream.ts`

This uses native `fetch` + `ReadableStream` (not `EventSource`) so we can pass the Bearer token via headers. No new dependencies needed.

```typescript
import { useEffect, useRef, useCallback, useState } from "react";

import { useAuthStore } from "@/auth/providers/auth-store";

interface UseAgentLogStreamOptions {
  agentId: string;
  enabled: boolean;
  onLine: (line: string) => void;
}

export function useAgentLogStream({
  agentId,
  enabled,
  onLine,
}: UseAgentLogStreamOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const onLineRef = useRef(onLine);
  onLineRef.current = onLine;

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    if (!enabled) {
      disconnect();
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    async function run() {
      const tokens = useAuthStore.getState().authToken;
      if (!tokens?.accessToken) return;

      try {
        const response = await fetch(
          `/api/v1/agents/${agentId}/logs/stream?tail_lines=0`,
          {
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: "text/event-stream",
            },
            signal: controller.signal,
          },
        );

        if (!response.ok || !response.body) return;
        setIsConnected(true);

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();

        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += value;
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            for (const line of part.split("\n")) {
              if (line.startsWith("data: ")) {
                onLineRef.current(line.slice(6));
              }
            }
          }
        }
      } catch (err) {
        if ((err as DOMException).name === "AbortError") return;
      } finally {
        setIsConnected(false);
      }
    }

    void run();
    return () => disconnect();
  }, [agentId, enabled, disconnect]);

  return { isConnected, disconnect };
}
```

Key design choices:
- `onLineRef` avoids recreating the connection when the callback identity changes
- `tail_lines=0` because initial lines come from the REST endpoint
- AbortController handles cleanup on unmount or `enabled` toggle
- No reconnect logic for MVP — the UI shows a "disconnected" state

---

## Sub-Task 9: UI — LogsTab Component

**File:** New `ui/src/features/agents/components/logs-tab.tsx`

```typescript
"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";

import type { Agent } from "../schemas";
import { useAgentLogs } from "../hooks/use-agent-logs";
import { useAgentLogStream } from "../hooks/use-agent-log-stream";

interface LogsTabProps {
  agent: Agent;
}

const MAX_BUFFER_LINES = 10_000;

export function LogsTab({ agent }: LogsTabProps) {
  const isRunning = agent.status === "RUNNING";
  const { logs, isLoading, error, refetch } = useAgentLogs(agent.id);
  const [lines, setLines] = useState<string[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevStatusRef = useRef(agent.status);

  // Seed lines from initial fetch
  useEffect(() => {
    if (logs?.lines) {
      setLines(logs.lines);
    }
  }, [logs]);

  // Refetch when agent transitions between running/stopped
  useEffect(() => {
    if (prevStatusRef.current !== agent.status) {
      prevStatusRef.current = agent.status;
      void refetch();
    }
  }, [agent.status, refetch]);

  const handleNewLine = useCallback((line: string) => {
    setLines((prev) => {
      const next = [...prev, line];
      return next.length > MAX_BUFFER_LINES
        ? next.slice(next.length - MAX_BUFFER_LINES)
        : next;
    });
  }, []);

  const { isConnected } = useAgentLogStream({
    agentId: agent.id,
    enabled: isRunning,
    onLine: handleNewLine,
  });

  // Auto-scroll when at bottom
  useLayoutEffect(() => {
    if (isAtBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, isAtBottom]);

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const threshold = 50;
    setIsAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < threshold);
  }

  function jumpToLatest() {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsAtBottom(true);
    }
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load logs"
        description="The log data is unavailable right now."
        onRetry={() => { void refetch(); }}
        retryLabel="Retry"
        className="min-h-[15rem] p-0"
      />
    );
  }

  return (
    <div className="relative">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2.5 rounded-t-xl"
        style={{ background: "var(--bg-soft)", borderBottom: "1px solid var(--line)" }}
      >
        <span className="text-[0.8125rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {logs?.source === "snapshot" && logs.sessionEndedAt
            ? `Session ended ${new Date(logs.sessionEndedAt).toLocaleString()}`
            : "Live logs"}
        </span>
        {isRunning && (
          <span className="flex items-center gap-1.5 text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: isConnected ? "var(--ok)" : "var(--ink-4)" }}
            />
            {isConnected ? "Streaming" : "Disconnected"}
          </span>
        )}
      </div>

      {/* Log viewport */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-y-auto font-mono text-[0.8125rem] leading-[1.6] px-4 py-3 rounded-b-xl"
        style={{
          background: "var(--bg-deep, #0d1117)",
          color: "var(--ink-on-deep, #c9d1d9)",
          height: "32rem",
          border: "1px solid var(--line)",
          borderTop: "none",
        }}
      >
        {isLoading && (
          <div className="text-center py-12" style={{ color: "var(--ink-4)" }}>
            Loading logs…
          </div>
        )}
        {!isLoading && lines.length === 0 && (
          <div className="text-center py-12" style={{ color: "var(--ink-4)" }}>
            No logs available
          </div>
        )}
        {lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all min-h-[1.6em]">
            {line || " "}
          </div>
        ))}
      </div>

      {/* Jump to latest button */}
      {!isAtBottom && lines.length > 0 && (
        <button
          onClick={jumpToLatest}
          className="absolute bottom-4 right-4 px-3 py-1.5 rounded-lg text-[0.75rem] font-medium shadow-md"
          style={{
            background: "var(--accent)",
            color: "var(--ink-on-accent, #fff)",
          }}
        >
          ↓ Jump to latest
        </button>
      )}
    </div>
  );
}
```

Component handles:
- **Loading**: "Loading logs…" placeholder
- **Empty**: "No logs available" message
- **Stopped agent**: Shows snapshot with session timestamp in header
- **Running agent**: Live streaming with connected/disconnected indicator
- **Smart auto-scroll**: Pauses on scroll-up, "Jump to latest" button
- **Buffer cap**: 10,000 lines max in memory

---

## Sub-Task 10: Wire LogsTab into Agent Detail Page

**File:** `ui/src/features/agents/components/agent-detail-page.tsx`

1. Add import:
```typescript
import { LogsTab } from "./logs-tab";
```

2. Update Tab type + valid tabs:
```typescript
type Tab = "conversations" | "tool-calls" | "logs" | "work" | "about";
const VALID_TABS: Tab[] = ["conversations", "tool-calls", "logs", "work", "about"];
```

3. Update the `tabs` display array — add `["logs", "Logs"]` between tool-calls and work:
```typescript
const tabs: [Tab, string][] = [
  ["conversations", "Conversations"],
  ["tool-calls", "Tool calls"],
  ["logs", "Logs"],
  ["work", "Work"],
  ["about", "About"],
];
```

4. Add the tab render:
```typescript
{tab === "logs" && <LogsTab agent={agent} />}
```

---

## Sub-Task 11: Playwright Tests

**File:** New `ui/tests/e2e/agent-logs.spec.ts`

- Test "Logs" tab appears in agent detail page
- Test clicking "Logs" tab shows the log viewer container
- Test "No logs available" message for agent with no snapshots
- Test SSE stream display with mocked endpoint (intercept `/logs/stream`)

---

## Verification

After all sub-tasks:
1. `make check-api` — ruff lint + format pass
2. `make test-api` — all unit + integration tests pass
3. `make lint-ui` — UI lint passes
4. `cd ui && pnpm -s tsc --noEmit` — TypeScript compiles
5. `make migrate` — migration applies cleanly
6. Manual: start agent → open Logs tab → see live streaming
7. Manual: stop agent → Logs tab shows historical snapshot
8. Manual: scroll up → auto-scroll pauses → "Jump to latest" appears → click returns to bottom
9. Manual: stop + start agent → previous session logs still accessible

---

## Implementation Order

```
1. K8s client log methods (+ unit tests)
2. DB model + migration
3. Repository methods (+ unit tests)
4. Service methods + stop_agent modification (+ unit tests)
5. Routes (+ integration tests)
6. UI schemas + query keys
7. useAgentLogs hook
8. useAgentLogStream hook
9. LogsTab component
10. Wire into agent-detail-page
11. Playwright tests
```

Sub-tasks 1–5 are sequential (API). Sub-tasks 6–10 are sequential (UI). Sub-task 6 can start as soon as Sub-task 2 defines the response shape. Tests are written before implementation in each sub-task per TDD.

---

# Bug Fixes (found during local testing)

Sub-tasks 1–10 are implemented and all tests pass. Three bugs found during local testing (API+DB+UI local, cluster remote).

## Bugs

1. **Logs don't stream in real-time** — user must refresh to see new lines
2. **"Streaming"/"Disconnected" indicator appears random** — no clear trigger
3. **Logs don't survive stop/start** — old session logs disappear after restart

## API Log Analysis

- Every `/logs/stream` request completes with 200 immediately (stream doesn't stay open)
- `/logs/stream` + `/logs` called ~15 times in pairs at ~10s intervals (component remounts on health polling re-renders)
- No `WARNING Failed to capture logs` during stop → capture either succeeded silently or returned early on empty `log_text`

## Root Causes

- **Next.js rewrite proxy buffers SSE** (Bug 1): `next.config.ts` proxies `/api/*` → backend via Node.js HTTP proxy, which accumulates the full response before forwarding. SSE never arrives in real-time. Confirmed by Next.js GitHub Issue #66263 ("browser receives data only after the response ends") and Discussion #76266 (identical rewrite pattern, same problem). No workaround exists for the rewrite proxy path — must bypass it entirely.
- ~~**urllib3 chunk buffering**~~: Originally suspected `for raw_line in resp:` used ~10KB chunks. **Disproved** — urllib3 2.x `__iter__` already splits on `\n` and yields complete lines (see urllib3 source `response.py`). The underlying `stream()` reads 64KB socket chunks but `read(amt)` returns as soon as data is available, so lines are yielded in real-time. No backend fix needed.
- **No reconnect / no "connecting" state** (Bug 2): Frontend SSE hook starts with `isConnected=false`, only becomes `true` after the fetch succeeds, and has no retry on disconnect. Confirmed by reading `use-agent-log-stream.ts`.
- **Live mode hides historical snapshots** (Bug 3): After restart, `get_agent_logs` sees `RUNNING` and returns only live pod logs from the new pod. Saved snapshots exist in DB but are never surfaced. Confirmed by reading `service.py` → `get_agent_logs`.

---

## Bug Fix 1: SSE hook must bypass the Next.js proxy

**File:** `ui/src/features/agents/hooks/use-agent-log-stream.ts`

The SSE `fetch()` call currently uses a relative URL `/api/v1/agents/...` which goes through the Next.js rewrite proxy. Change it to use `NEXT_PUBLIC_BACKEND_URL` directly for the SSE connection, bypassing the proxy. REST calls can stay on the proxy (they don't need streaming).

- Read `process.env.NEXT_PUBLIC_BACKEND_URL` (falls back to empty string for production where both run behind the same reverse proxy)
- Build the SSE URL as `${backendUrl}/api/v1/agents/${agentId}/logs/stream?tail_lines=0`

## ~~Bug Fix 2: Use line-based reading in K8s client~~ — REMOVED

Disproved during root cause verification. urllib3 2.x `__iter__` already yields complete lines split on `\n`. No backend change needed.

## Bug Fix 3: Add reconnect logic and "Connecting" state

**File:** `ui/src/features/agents/hooks/use-agent-log-stream.ts`

- Add a `"connecting"` state so the UI can show "Connecting..." instead of "Disconnected" during the initial fetch
- Auto-reconnect with exponential backoff when the connection drops (unless explicitly aborted via unmount)
- Expose connection state as a union type `"idle" | "connecting" | "streaming" | "disconnected"` instead of boolean

**File:** `ui/src/features/agents/components/logs-tab.tsx`

- Update the status indicator to show "Connecting..." when state is `"connecting"`, "Streaming" when `"streaming"`, "Disconnected" when `"disconnected"`

## Bug Fix 4: Logs don't survive stop/start cycles

Two sub-issues:

**4a: Add success logging to `_capture_logs_before_stop`**

**File:** `api/domains/agents/service.py` → `_capture_logs_before_stop`

Add `logger.info` when a snapshot is successfully saved, and `logger.info` when `log_text` is empty (returns early). This lets us confirm whether capture works or silently skips.

**4b: After restart, live mode hides historical snapshots**

**File:** `api/domains/agents/service.py` → `get_agent_logs`

Currently when `agent.status == RUNNING`, the method only returns live pod logs. After a restart, the new pod only has post-restart logs — old session logs are invisible even though they're saved in the DB.

Fix: Add a `has_snapshots: bool = False` field to `AgentLogsRead` that is `True` when the agent has at least one saved snapshot. Populate it with a `repository.get_latest_log_snapshot(agent_id) is not None` check in both the running and stopped branches.

**File:** `api/domains/agents/models.py` → `AgentLogsRead`

Add `has_snapshots: bool = False` field.

**File:** `ui/src/features/agents/schemas.ts` → `AgentLogsReadSchema`

Add `hasSnapshots: z.boolean().optional().default(false)` field.

**File:** `ui/src/features/agents/components/logs-tab.tsx`

When `logs.hasSnapshots` is true and agent is running, show a "Previous sessions available" note at the top of the log viewport. For MVP, this is informational only.

## Bug Fix Implementation Order

1. Bug Fix 4a (backend: add logging to capture method)
2. Bug Fix 4b (backend+frontend: has_snapshots field)
3. Bug Fix 1 + 3 (frontend: bypass proxy + reconnect + connection states)

## Bug Fix Verification

1. Start the UI dev server and API locally
2. Open agent detail → Logs tab for a running agent
3. Trigger agent activity (send a message)
4. Confirm new log lines appear in real-time without page refresh
5. Confirm indicator shows "Connecting..." → "Streaming"
6. Kill and restart the API — confirm the hook reconnects automatically
7. Stop agent → confirm API logs show "Captured log snapshot for agent ..."
8. Start agent again → confirm "Previous sessions available" note appears
9. Run existing unit tests to check for regressions
