# Push-Based Conversation and Tool Call Logging

## Context

Currently, conversations and tool calls are fetched by kubectl-exec'ing into agent pods to read JSONL session files. This is fragile (depends on pod being live), adds latency (triggered on-demand when the UI requests data), and couples the API to filesystem details of two different agent runtimes.

The goal is to replace this with a push-based model: plugins inside agent pods intercept messages and tool calls in real-time and POST them to an internal-only ingest endpoint on the API server. The pull-based kubectl exec sync is removed entirely.

## Decisions

- **Ingest endpoint**: Second FastAPI app on port 8001 in the same container. Port 8001 is added to the k8s Service (for in-cluster DNS) but NOT to the Ingress (so it's unreachable from outside the cluster).
- **Auth**: Per-agent ingest key generated at start time, stored encrypted in the agent table, injected as env var. Verified via constant-time comparison on each request.
- **Agent plugins**: Hermes (Python) and OpenClaw (TypeScript). Hook APIs verified — see "Verified Hook Signatures" section below.
- **Pull removal**: Per acceptance criteria ("kubectl exec is no longer used for fetching messages and tool calls"), the pull-based sync code is removed in this task — not a follow-up.
- **Name resolution**: Plugins send IDs only (sender_id, channel_id). The IngestService resolves display names server-side using the existing `SlackClient` + cached directory (same approach as the current pull-based sync).

---

## Verified Hook Signatures

### Hermes (Python) — source: hermes-agent.nousresearch.com/docs/user-guide/features/hooks

**`pre_gateway_dispatch(event, gateway, session_store, **kwargs)`**
- `event.text` — message content
- `event.source.platform` — "slack", etc.
- `event.source.chat_type` — "dm" or "channel"  
- `event.source.user_id` — sender ID
- `event.source.chat_id` — channel ID
- `event.message_id` — platform message ID (may exist)
- No guaranteed unique msg_id → generate deterministic ID from `f"{session_id}:{hash(content+timestamp)}"`

**`post_llm_call(session_id, user_message, assistant_response, conversation_history, model, platform, **kwargs)`**
- `assistant_response` — agent's final response text (outbound message content)
- `session_id` — session identifier
- No msg_id → generate deterministic ID same as above

**`pre_tool_call(tool_name, args, task_id, **kwargs)`**
- `tool_name` — tool identifier (e.g., "terminal", "read_file")
- `args` — arguments dict passed by the model
- `task_id` — session identifier
- Return `{"action": "block", ...}` to veto; return None to pass through

**`post_tool_call(tool_name, args, result, task_id, duration_ms, **kwargs)`**
- `result` — tool's return value (JSON string)
- `duration_ms` — execution time in milliseconds
- Observer-only (return value ignored)

**`on_session_end(session_id, completed, interrupted, model, platform, **kwargs)`**
- Used for final buffer flush before session teardown

### OpenClaw (TypeScript) — source: docs.openclaw.ai/plugins/hooks

**`message_received` (Observation)**
- `content`, `sender`, `threadId`, `messageId`, `senderId`
- Context: `ctx.sessionKey`, `ctx.channelId`, `ctx.agentId`
- `messageId` available for dedup

**`message_sent` (Observation)**
- Final success/failure status, delivery metadata
- Fire-and-forget; handler failures are logged

**`before_tool_call` (Decision)**
- `event.toolName`, `event.params`, `event.toolCallId`, `event.runId`
- Context: `ctx.agentId`, `ctx.sessionKey`, `ctx.sessionId`
- Return `{}` or `undefined` for observation-only (no blocking)

**`after_tool_call` (Observation)**
- Tool results, errors, duration
- `event.toolCallId` for correlation with before_tool_call

**`session_end` (Observation)**
- Used for final buffer flush

---

## Sub-tasks (in order)

### 1. DB migration + Agent model change
- Add `ingest_key_encrypted: str | None` column to `Agent` model in `api/domains/agents/models.py`
- Create Alembic migration (nullable column, no data migration needed)
- Files: `api/domains/agents/models.py`, `api/migrations/versions/<new>.py`

### 2. Ingest domain (models, service, routes)
Create `api/domains/ingest/` following AGENTS.md domain playbook:

**`models.py`** — request/response models:
- `IngestBatchRequest` containing lists of `IngestMessageEvent`, `IngestToolCallEvent`, `IngestToolResultEvent`
- See "Payload Schema" section below for exact fields

**`service.py`** — `IngestService` with:
- `authenticate(agent_id, authorization_header)` — load agent, decrypt `ingest_key_encrypted`, constant-time compare with `secrets.compare_digest()`
- `process(agent_id, batch)` — convert events to existing model objects, delegate to existing repos:
  - Messages → `AgentChatMessage` objects → `ConversationRepository.upsert_messages()`
  - Tool calls → `ToolCallRepository.upsert_pending()`
  - Tool results → `ToolCallRepository.complete()`
- Name resolution: for messages with `sender_id`/`channel_id` but no names, call `SlackClient` to resolve (using the agent's decrypted bot token, same as `ConversationSyncService._platform_maps()`)

**`routes.py`** — single endpoint:
- `POST /agents/{agent_id}/events` → 204 on success, 401 on bad auth

### 3. Ingest FastAPI app + process startup
- Create `api/ingest_app.py` — minimal FastAPI app (no CORS, no lifespan bootstrap), mounts ingest routes at `/ingest/v1`, shares injector with main app
- Create `api/ingest_main.py` — entrypoint: `app = create_ingest_app()`
- Add `ingest_base_url` to `api/core/config.py` (default: `http://agentfarm-api.agent-farm.svc.cluster.local:8001/ingest/v1`)
- Create `api/start.sh` — entrypoint script:
  ```sh
  #!/bin/sh
  uvicorn api.ingest_main:app --host 0.0.0.0 --port 8001 &
  exec fastapi run api/main.py --port 8000
  ```
- Update `api/Dockerfile`:
  - Add `EXPOSE 8001`
  - Change CMD from `["fastapi", "run", "api/main.py", "--port", "8000"]` to `["sh", "api/start.sh"]`
  - Copy `api/start.sh` into the image

### 4. Builder changes (env vars + key generation)
In `start_agent` (`api/domains/agents/service.py`):
- Generate ingest key: `secrets.token_urlsafe(32)`
- Encrypt and store: `agent.ingest_key_encrypted = encrypt_token(key, self.config.agent_token_encryption_key)`
- Save agent record

Add three env vars to ALL secret builders:
- `AGENT_ID` — the agent's UUID string
- `INGEST_URL` — from `config.ingest_base_url`
- `INGEST_API_KEY` — the plaintext ingest key

Files to modify:
- `api/domains/agents/builders/hermes.py` — `build_secret_hermes_slack()` string_data
- `api/domains/agents/builders/openclaw.py` — `build_secret_slack()` and `build_secret_teams()` string_data
- `api/domains/agents/service.py` — key generation in start_agent, pass key + URL to builder calls

### 5. Hermes telemetry-push plugin
Create `api/domains/agents/scripts/hermes/plugins/telemetry-push/`:

**`plugin.yaml`**:
```yaml
name: telemetry-push
version: "1.0"
description: Push messages and tool calls to the ingest API
```

**`__init__.py`** — registers 5 hooks:
- `pre_gateway_dispatch` → capture inbound messages (event.text, event.source.user_id, event.source.chat_id, event.source.chat_type)
- `post_llm_call` → capture outbound messages (assistant_response, session_id)
- `pre_tool_call` → capture tool call start (tool_name, args, task_id). Generate external_id: `f"{task_id}:{tool_name}:{hash(json.dumps(args, sort_keys=True))}:{time.time()}"`
- `post_tool_call` → capture tool call result (tool_name, result, duration_ms). Correlate with pre_tool_call via matching external_id
- `on_session_end` → flush buffer immediately before session teardown

**Buffer/flush design** (stdlib only — `urllib.request`, `json`, `threading`, `time`):
- Thread-safe list protected by `threading.Lock`
- Daemon thread flushes every 2 seconds OR when buffer hits 50 events
- `on_session_end` triggers immediate synchronous flush
- All HTTP errors are caught and logged, never propagated
- Reads `AGENT_ID`, `INGEST_URL`, `INGEST_API_KEY` from env vars; if any missing, `register()` returns immediately (plugin disables itself)

**Dedup ID generation for Hermes** (no native msg_id available):
- Messages: `f"hermes:{session_id}:{direction}:{int(occurred_at.timestamp()*1000)}"`
- Tool calls: `f"hermes:{task_id}:{tool_name}:{int(time.time()*1000)}:{monotonic_counter}"`
- These become `openclaw_msg_id` / `external_id` in the DB, caught by existing unique constraints

**Builder/config changes**:
- Add `"telemetry-push"` to `enabled_plugins` list in `build_hermes_config()` (unconditionally — plugin self-disables via env check)
- Add plugin files to ConfigMap in `build_hermes_config_map()`
- Add copy lines to `start.sh`:
  ```sh
  mkdir -p /opt/data/plugins/telemetry-push
  cp /app/config/telemetry-push-plugin.yaml /opt/data/plugins/telemetry-push/plugin.yaml
  cp /app/config/telemetry-push-init.py /opt/data/plugins/telemetry-push/__init__.py
  ```

### 6. OpenClaw telemetry-push plugin
Create `api/domains/agents/scripts/openclaw/plugins/telemetry-push/`:

**`package.json`**:
```json
{
  "name": "telemetry-push",
  "version": "1.0.0",
  "type": "module",
  "openclaw": {
    "extensions": ["./index.js"]
  }
}
```

**`openclaw.plugin.json`**:
```json
{
  "id": "telemetry-push",
  "name": "Telemetry Push",
  "description": "Push messages and tool calls to the ingest API",
  "activation": { "onStartup": true },
  "configSchema": { "type": "object", "additionalProperties": false }
}
```

**`index.js`** — registers 5 hooks via `api.on()`:
- `message_received` → capture inbound (content, senderId, messageId, ctx.channelId, ctx.sessionKey, threadId)
- `message_sent` → capture outbound (content, messageId, ctx.channelId, ctx.sessionKey)
- `before_tool_call` → capture tool call start (event.toolName, event.params, event.toolCallId, ctx.sessionKey)
- `after_tool_call` → capture tool result (event.toolCallId for correlation, results, errors, duration)
- `session_end` → flush buffer immediately

**Buffer/flush design** (Node stdlib only — `http` or `https`):
- Array buffer, flushed by `setInterval` every 2 seconds
- `session_end` handler triggers immediate flush
- All HTTP errors caught and logged via `api.logger.warn()`
- Reads `AGENT_ID`, `INGEST_URL`, `INGEST_API_KEY` from `process.env`; if missing, `register()` returns early

**Installation in container**:
- Plugin files are added to ConfigMap via `build_config_map()` in `openclaw.py`
- `init-openclaw.js` is updated to copy plugin files to a local directory (e.g., `/home/node/.openclaw/local-plugins/telemetry-push/`)
- `start.sh` is updated to run `openclaw plugins install /home/node/.openclaw/local-plugins/telemetry-push` before `exec openclaw gateway`
- Config overlay builders add `"telemetry-push"` to `plugins.allow` and `plugins.entries` with `{ "enabled": true }`

### 7. Remove pull-based sync (kubectl exec)
Per acceptance criteria: "Kubectl exec is no longer used for fetching messages and tool calls."

**Delete entirely**:
- `api/domains/tool_calls/sync_service.py` — `ToolCallSyncService` class (all kubectl exec for tool calls)
- `api/domains/conversations/service.py` — `ConversationSyncService` class (all kubectl exec for messages)
- `api/domains/tool_calls/models.py` — `ToolCallSyncState` model (tracks byte offsets for incremental pull)
- Create Alembic migration to drop `tool_call_sync_state` table

**Simplify `ToolCallService`** (`api/domains/tool_calls/service.py`):
- Remove `sync_service` dependency and `_executor` field
- `list_tool_calls()` becomes a direct DB read — remove the `self._executor.submit(self.sync_service.sync_agent, ...)` call
- Just return `self.repository.find_by_agent(agent_id, filter, pagination)`

**Simplify `ConversationService`** (`api/domains/conversations/service.py`):
- Remove `sync_service` dependency
- `list_channels()` — remove the pod-read branch that calls `_read_sessions_json()` / `_read_hermes_sessions_json()` via kubectl exec. Only read from DB.
- `list_threads()` — remove the `submit_sync_channel()` call. Only read from DB.

**Simplify `stop_agent`** (`api/domains/agents/service.py`, lines 796-826):
- Remove the entire pre-deletion sync block (futures, wait, timeout). Push handles real-time delivery; no need to flush from pod before teardown.
- Remove `conversation_sync_service` and `sync_service` fields from `AgentService`
- Remove imports of `ConversationSyncService` and `ToolCallSyncService`

**Clean up**:
- Remove `ToolCallSyncService` import from `api/domains/tool_calls/__init__.py` if barrel-exported
- Remove `ConversationSyncService` re-export from `api/domains/conversations/service.py` `__all__`
- Update any tests that reference sync services or `ToolCallSyncState`
- Remove unused parsers only if they're exclusively used by sync (check: `jsonl_parser.py`, `hermes_parser.py`, `parser.py` may still be needed if referenced elsewhere)

### 8. Tests
- **Unit**: IngestService.authenticate (valid key, wrong key, missing agent, no key on agent)
- **Unit**: IngestService.process (message upsert, tool call upsert, tool result completion, empty batch, dedup — same event twice)
- **Unit**: Hermes plugin buffer/flush logic (can be tested in isolation as pure Python)
- **Integration**: POST to `/ingest/v1/agents/{agent_id}/events` with valid auth → data in DB
- **Integration**: POST with wrong key → 401
- **Integration**: POST duplicate events → no duplicates in DB
- **Removal**: Update/remove existing tests that depend on `ToolCallSyncService`, `ConversationSyncService`, or `ToolCallSyncState`
- Follow existing test patterns: `given/when/then` style, `prepare_injector()`, `create_test_client()`, etc.

### 9. Helm adjustments
- `helm/agentfarm-api/templates/deployment.yaml` — add `containerPort: 8001` named `ingest` to container ports list
- `helm/agentfarm-api/templates/service.yaml` — add second port: `port: 8001, targetPort: 8001, name: ingest` (required so agent pods can reach it via `agentfarm-api.agent-farm.svc.cluster.local:8001`)
- `helm/agentfarm-api/templates/ingress.yaml` — NO changes (ingress only routes to the `http` port, so port 8001 stays cluster-internal)
- `helm/agentfarm-api/values.yaml` — add `ingestPort: 8001`

---

## Payload Schema

```python
class IngestMessageEvent(PydanticBaseModel):
    msg_id: str                          # dedup key (→ openclaw_msg_id column)
    session_key: str                     # e.g. "agent:main:slack:channel:C12345"
    channel_id: str                      # uppercased Slack channel/DM ID
    thread_id: str | None = None
    direction: MessageDirection           # INBOUND / OUTBOUND
    conversation_type: ConversationType   # CHANNEL / DM
    sender_id: str | None = None         # Slack user ID (name resolved server-side)
    channel_name: str | None = None      # optional, resolved server-side if missing
    sender_name: str | None = None       # optional, resolved server-side if missing
    content: str
    occurred_at: datetime

class IngestToolCallEvent(PydanticBaseModel):
    external_id: str                     # dedup key (→ external_id column)
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    occurred_at: datetime

class IngestToolResultEvent(PydanticBaseModel):
    external_id: str                     # matches the IngestToolCallEvent
    result: Any | None = None
    is_error: bool = False
    completed_at: datetime

class IngestBatchRequest(PydanticBaseModel):
    messages: list[IngestMessageEvent] = []
    tool_calls: list[IngestToolCallEvent] = []
    tool_results: list[IngestToolResultEvent] = []
```

Single endpoint: `POST /ingest/v1/agents/{agent_id}/events`

---

## Key Patterns to Reuse

- **Hermes plugin structure**: follow `api/domains/agents/scripts/hermes/plugins/slack-deny-dms/` exactly (plugin.yaml + __init__.py + register(ctx))
- **ConfigMap injection**: both builders already bake plugin files into ConfigMaps
- **Env var injection**: both secret builders already inject env vars into agent pods via k8s Secret
- **Repository upsert**: `ConversationRepository.upsert_messages()`, `ToolCallRepository.upsert_pending()` / `.complete()` — idempotent, dedup via unique constraints
- **DI pattern**: `@inject @singleton @dataclass` with `fastapi-injector`
- **Fernet encryption**: `api/infrastructure/crypto.py` — `encrypt_token()` / `decrypt_token()`
- **Slack name resolution**: Extract the `_platform_maps()` logic from `ConversationSyncService` into `IngestService` before deleting the sync service — decrypt bot token, call SlackClient, build user_map/channel_map

---

## Verification

1. Run `make test-api` after each sub-task
2. Run `make check-api` for lint/type checks
3. Start a Hermes agent → verify ingest endpoint receives events → data appears in conversations/tool-calls UI
4. Start an OpenClaw agent → verify the same
5. Verify port 8001 is NOT reachable from outside the cluster (curl from external → connection refused)
6. Verify no remaining references to `ToolCallSyncService`, `ConversationSyncService`, or kubectl exec for message/tool-call fetching
