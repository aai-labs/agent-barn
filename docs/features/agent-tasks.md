# Agent Tasks

## Read when

Read before changing Tasks, Task Notes, Task Files, their storage or limits, or who can read them.

## Role in the system

A Task is a piece of work an Agent records for itself, with a timeline of Task Notes and the Task Files it produces. Tasks live in Agent Barn's own tables in the application Postgres, not in a separate tracker; [`../adr/2026-10-21-native-agent-task-store.md`](../adr/2026-10-21-native-agent-task-store.md) records why.

This slice is the store and its service (`../api/domains/agent_tasks/`). It has no HTTP routes, Agent tooling or UI yet.

## Invariants

- A Task belongs to one Agent and carries the same Organization identity. The database enforces this with a composite foreign key to the Agent.
- A Task has a title, an optional description, and a status of `open`, `in_progress`, `done` or `failed`. It starts `open`, and its Agent may move it to any status.
- Task Notes are append-only and listed oldest first.
- Only the Task's own Agent writes: it creates Tasks, changes their status, adds Notes and attaches Files. The write methods take the Agent's Organization and id, which the caller has already authenticated, and refuse a deleted Agent or another Agent's Task with 404. People have no write path.
- People read Tasks with `task.read`, which every locked Agent Access Role grants. Reads filter by Agent visibility in the query: one Agent's Tasks, one Task with its Notes and File metadata, one File's bytes, or every Task across the Organization the reader can see. Lists are newest first and can be filtered by Agent and status; an Agent the reader cannot see simply yields no Tasks. An Agent the reader cannot see returns 404; one they can see without `task.read` returns 403. See [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md).

## Task Files

- A Task File's metadata (name, content type, size) sits in `agent_task_file`; its bytes sit behind the `TaskFileStorage` interface (`../api/domains/agent_tasks/file_storage.py`), keyed by File id. Tasks never touch the bytes, so moving them to object storage replaces that store and its binding in `../api/infrastructure/app.py`.
- Uploads stream: `attach_file` takes the upload as an iterable of byte pieces and both limits are checked as it is read, so an oversized upload stops at the limit rather than being read whole. The Postgres store re-cuts the stream into 1 MiB chunks in `agent_task_file_chunk`, flushing each, then records the File row with the total size in the same transaction. The chunk foreign key is checked at commit for that reason. Chunks go with their File by cascade.
- A File's Organization is always its Task's: a composite foreign key enforces it, so bytes are counted against the right limit.
- A filename is a plain name: not `.` or `..`, and no path separators, quotes, control characters or Unicode direction marks. A content type is a bare `type/subtype` without parameters. Both come from the Agent, so they are untrusted; a download route must still serve Files as attachments with `X-Content-Type-Options: nosniff`, whatever type was stored.
- Empty files are refused. A File may be at most `TASK_FILE_MAX_BYTES` (default 20 MiB), and one Organization's Task Files together at most `TASK_ORGANIZATION_STORAGE_MAX_BYTES` (default 2 GiB). Both are refused with 400. A per-Organization advisory lock makes the usage check and the insert one step, so concurrent uploads cannot together pass the limit.
- `read_file` returns the File's metadata and a lazy stream of its bytes. If the Agent is deleted while a download is in progress, the stream ends early; a download route has to treat fewer bytes than `size_bytes` as a failed response.

## Deletion

Agent deletion is a soft delete, so the Agent foreign key never cascades. The deletion transaction in `AgentRepository.soft_delete_with_event` calls `stage_agent_task_cleanup` (`../api/domains/agent_tasks/cleanup.py`), which deletes the Agent's Tasks; their Notes, Files and chunks follow by cascade. If the deletion rolls back, the Tasks stay. Agent writes hold the Agent row `FOR KEY SHARE`, which conflicts with the deletion's `FOR UPDATE` but not with ordinary Agent updates, so no Task can be added after the cleanup ran and a long upload does not hold up the Agent.
