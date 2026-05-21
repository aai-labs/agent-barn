# Plan: Chat History — Conversations Tab

## Context

Agents run as standalone pods communicating directly with Slack via Socket Mode.
All conversation data lives in JSONL files on each agent pod's PVC at
`/home/node/.openclaw/agents/main/sessions/`. Because agentfarm-api never sees
messages in-flight, the only read path is `kubectl exec … cat <file>`.

We parse and persist that data into the agentfarm-api Postgres DB on two hooks:
when the UI requests conversation history (so running agents surface live data)
and when an agent is stopped (so stopped agents still have something to show).

The UI replaces the "Coming soon" ConversationsTab with a two-panel layout:
channels on the left, a message list on the right where top-level channel
interactions and threads are shown inline.

---

## JSONL Schema (ground truth from live pod)

**sessions.json** — index keyed by session_key:
```json
{
  "agent:main:slack:channel:c0b4w57jvez": {
    "sessionId": "<uuid>",
    "chatType": "channel",
    "groupId": "c0b4w57jvez",
    "origin": { "nativeChannelId": "C0B4W57JVEZ", "threadId": null }
  },
  "agent:main:slack:channel:c0b4w57jvez:thread:1779269814.824809": {
    "sessionId": "<uuid>",
    "groupId": "c0b4w57jvez",
    "origin": { "nativeChannelId": "C0B4W57JVEZ", "threadId": "1779269814.824809" }
  }
}
```

**Per-session `<uuid>.jsonl`** — relevant line types:

| Detect by | Direction | Extract |
|-----------|-----------|---------|
| `type=custom_message`, `customType=openclaw.runtime-context` | INBOUND | Parse `content` with regex: `\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] Slack message in #\w+ from (\w+): (.+)` → timestamp, sender_id, text |
| `type=message`, `message.role=assistant`, `message.model=delivery-mirror`, `content[0].type=text` | OUTBOUND | `message.content[0].text`, timestamp from line's ISO timestamp |

Each line has a stable `id` field (short hex or UUID) used for upsert dedup.

---

## Database

### New table: `agent_chat_message`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | uuid7 via BaseModel |
| `created_at` / `updated_at` | timestamptz | BaseModel |
| `agent_id` | UUID FK → `agent.id` CASCADE | |
| `openclaw_msg_id` | TEXT | line `id` from JSONL — dedup key |
| `session_key` | TEXT | full openclaw key |
| `channel_id` | TEXT | uppercase Slack channel ID, e.g. `C0B4W57JVEZ` |
| `thread_id` | TEXT nullable | Slack thread root timestamp; NULL = top-level channel |
| `direction` | ENUM(`INBOUND`,`OUTBOUND`) | |
| `sender_id` | TEXT nullable | Slack user ID for INBOUND |
| `content` | TEXT | message text |
| `occurred_at` | timestamptz | actual Slack event time |

**Indexes:**
- UNIQUE `(agent_id, openclaw_msg_id)` — upsert dedup
- `(agent_id, channel_id)` — list by channel
- `(agent_id, session_key)` — fetch one session

### Migration file
`api/migrations/versions/f2c8a14e9b37_add_agent_chat_message.py`
— `down_revision = "e9b4f23c5a71"` (current head)

---

## Backend

### New files

**`api/domains/conversations/models.py`**
- `MessageDirection(str, Enum)`: `INBOUND`, `OUTBOUND`
- `AgentChatMessage(BaseModel, table=True)` — matches schema above
- `ConversationMessageRead` — subset for API response
- `ConversationSessionRead` — `session_key`, `channel_id`, `thread_id`, `messages`
- `ConversationChannelRead` — `channel_id`, `sessions`
- `ConversationsRead` — `channels`

**`api/domains/conversations/repository.py`**
- `upsert_messages(messages)` — INSERT … ON CONFLICT (agent_id, openclaw_msg_id) DO NOTHING
- `find_by_agent(agent_id)` — all messages ordered by occurred_at

**`api/domains/conversations/parser.py`**
- `parse_sessions(agent_id, sessions_json, get_jsonl)` — pure function, no I/O
- Extracts INBOUND (custom_message/runtime-context) and OUTBOUND (delivery-mirror) messages

**`api/domains/conversations/service.py`**
- `sync(agent_id, org_id)` — kubectl exec reads JSONL, calls parser, upserts to DB
- `get_conversations(agent_id, org_id)` — sync if RUNNING, then serve from DB

**`api/domains/conversations/routes.py`**
- `GET /api/v1/agents/{agent_id}/conversations` → `ConversationsRead`

### Modified files

**`api/api_app.py`** — register `conversations_router`

**`api/domains/agents/service.py` → `stop_agent`** — sync conversations before deleting deployment (best-effort, never blocks stop)

---

## Frontend

**`ui/src/features/agents/hooks/use-conversations.ts`** — React Query hook

**`ui/src/features/agents/components/conversations-tab.tsx`** — replace "Coming soon":
- Left sidebar: channel list
- Right panel: flat message list per channel, threads shown as indented expandable blocks
- Loading / empty / error states

---

## Verification

1. `cd api && uv run pytest tests/` — all green
2. `GET /api/v1/agents/{id}/conversations` → 200 with populated data
3. Stop agent → endpoint still returns data from DB
4. UI Conversations tab shows channels and messages
