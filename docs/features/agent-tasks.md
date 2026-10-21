# Agent Tasks

## Read when

Read before changing Tasks, Task Notes, Task Files, their storage or limits, or who can read them.

## Role in the system

A Task is a piece of work an Agent records for itself, with a timeline of Task Notes and the Task Files it produces. Tasks live in Agent Barn's own tables in the application Postgres, not in a separate tracker; [`../adr/2026-10-21-native-agent-task-store.md`](../adr/2026-10-21-native-agent-task-store.md) records why.

The store and its service live in `../api/domains/agent_tasks/`. Agents write and read their own Tasks through the routes and command below; there is no UI yet.

## Invariants

- A Task belongs to one Agent and carries the same Organization identity. The database enforces this with a composite foreign key to the Agent.
- A Task has a title, an optional description, and a status of `open`, `in_progress`, `done` or `failed`. It starts `open`, and its Agent may move it to any status.
- Task Notes are append-only and listed oldest first.
- Only the Task's own Agent writes: it creates Tasks, changes their status, adds Notes and attaches Files. The write methods take the Agent's Organization and id, which the caller has already authenticated, and refuse a deleted Agent or another Agent's Task with 404. People have no write path.
- People read Tasks with `task.read`, which every locked Agent Access Role grants. Reads filter by Agent visibility in the query: one Agent's Tasks, one Task with its Notes and File metadata, one File's bytes, or every Task across the Organization the reader can see. Lists are newest first and can be filtered by Agent and status; an Agent the reader cannot see simply yields no Tasks. An Agent the reader cannot see returns 404; one they can see without `task.read` returns 403. See [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md).

## How an Agent records Tasks

- Every Agent, on both Hermes and OpenClaw, runs the `agentbarn-tasks` plugin (`../api/domains/agents/scripts/hermes/plugins/agentbarn-tasks/`, `../api/domains/agents/scripts/openclaw/plugins/agentbarn-tasks/`), enabled for every Agent. Keeping Tasks does not rest on the prompt alone:
  - It registers an `agentbarn_task` tool with typed actions (`create`, `status`, `note`, `attach`, `list`, `show`). The tool runs `agentbarn-task` underneath, so the command stays the one client of the routes.
  - Each turn starts with the Agent's open and in-progress Tasks (cached for a minute, and refreshed after any Task change), so a stale `in_progress` Task stays in front of the model. Hermes adds them in `pre_llm_call`, OpenClaw in `before_prompt_build`.
  - It counts a turn's tool calls. Once a turn makes three or more without touching a Task, the plugin reminds the model once within the turn: Hermes appends the reminder to the next tool result (`transform_tool_result`; its `pre_verify` fires only after file edits), and OpenClaw asks for one more pass before finishing (`before_agent_finalize` returning `revise`). If the turn still ends without a Task, the next turn of that session carries a reminder. Heartbeat runs are not counted.
  - It never records a Task itself; the Agent writes every Task.
  - On OpenClaw the manifest declares the tool under `contracts.tools`, and the plugin's entry sets `hooks.allowConversationAccess`; without it OpenClaw drops the turn hooks with only a warning.
- Every Agent also has `/usr/local/bin/agentbarn-task` (`../api/domains/agents/scripts/agentbarn_task.py`, mounted from the Agent's ConfigMap by `../api/domains/agents/builders/tasks.py`). `AGENTS.md` carries `TASK_TOOL_INSTRUCTIONS`: keep a Task for any non-trivial request, check `list` before opening a new one, keep its status current, add notes and attach the files it produces. Unlike Agent Memory, there is no per-Agent switch.
- The command calls the Agent's Task routes on the ingest app (`../api/domains/agent_tasks/agent_routes.py`, mounted by `../api/ingest_app.py`) with the pod's `AGENT_ID`, `INGEST_URL` and `INGEST_API_KEY`. The ingest app is where Agents authenticate with their ingest key; the main API authenticates people. The routes belong to this domain and only borrow the key check (`authenticated_agent` in `../api/domains/ingest/service.py`).
- Routes under `/ingest/v1/agents/{agent_id}/tasks`: `POST` creates, `GET` lists (newest first, filter by `status`), `GET /{task_id}` shows one Task with its Notes and File metadata, `PATCH /{task_id}` sets the status, `POST /{task_id}/notes` adds a Note and `POST /{task_id}/files?filename=…` uploads a File. The Agent and its Organization always come from the key, never from the request, so an Agent only ever reaches its own Tasks; another Agent's Task is 404.
- An upload is the raw request body, with the File's content type in `Content-Type`. The route streams the body into `attach_file` through a worker-thread bridge, so it is never held whole. A declared `Content-Length` past the per-file limit is refused before reading. A refusal part way through reads and drops the rest of the body, at most the per-file limit, so the Agent gets the 400 rather than a reset connection. The command also refuses a file past `TASK_FILE_MAX_BYTES`, which the pod secret carries, before sending it.
- The command passes a 400 or 422 explanation through to the Agent and maps 401 and 404 to fixed messages; anything else is reported as unconfirmed, never as success.

## Task Files

- A Task File's metadata (name, content type, size) sits in `agent_task_file`; its bytes sit behind the `TaskFileStorage` interface (`../api/domains/agent_tasks/file_storage.py`), keyed by File id. Tasks never touch the bytes, so moving them to object storage replaces that store and its binding in `../api/infrastructure/app.py`.
- Uploads stream: `attach_file` takes the upload as an iterable of byte pieces and both limits are checked as it is read, so an oversized upload stops at the limit rather than being read whole. The Postgres store re-cuts the stream into 1 MiB chunks in `agent_task_file_chunk`, flushing each, then records the File row with the total size in the same transaction. The chunk foreign key is checked at commit for that reason. Chunks go with their File by cascade.
- A File's Organization is always its Task's: a composite foreign key enforces it, so bytes are counted against the right limit.
- A filename is a plain name: not `.` or `..`, and no path separators, quotes, control characters or Unicode direction marks. A content type is a bare `type/subtype` without parameters. Both come from the Agent, so they are untrusted; a download route must still serve Files as attachments with `X-Content-Type-Options: nosniff`, whatever type was stored.
- Empty files are refused. A File may be at most `TASK_FILE_MAX_BYTES` (default 20 MiB), and one Organization's Task Files together at most `TASK_ORGANIZATION_STORAGE_MAX_BYTES` (default 2 GiB). Both are refused with 400. A per-Organization advisory lock makes the usage check and the insert one step, so concurrent uploads cannot together pass the limit.
- `read_file` returns the File's metadata and a lazy stream of its bytes. If the Agent is deleted while a download is in progress, the stream ends early; a download route has to treat fewer bytes than `size_bytes` as a failed response.

## Deletion

Agent deletion is a soft delete, so the Agent foreign key never cascades. The deletion transaction in `AgentRepository.soft_delete_with_event` calls `stage_agent_task_cleanup` (`../api/domains/agent_tasks/cleanup.py`), which deletes the Agent's Tasks; their Notes, Files and chunks follow by cascade. If the deletion rolls back, the Tasks stay. Agent writes hold the Agent row `FOR KEY SHARE`, which conflicts with the deletion's `FOR UPDATE` but not with ordinary Agent updates, so no Task can be added after the cleanup ran and a long upload does not hold up the Agent.
