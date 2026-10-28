# Agent Tasks

## Read when

Read before changing Tasks, Task Notes, Task Files, how Task Files use Artifacts, or who can read them.

## Role in the system

A Task is a piece of work an Agent records for itself, with a timeline of Task Notes and the Task Files it produces. Tasks live in Agent Barn's own tables in the application Postgres, not in a separate tracker, and their files are [Artifacts](agent-artifacts.md); [`../adr/2026-10-21-native-agent-task-store.md`](../adr/2026-10-21-native-agent-task-store.md) records why.

This slice is the store and its service (`../api/domains/agent_tasks/`). It has no HTTP routes, Agent tooling or UI yet.

## Invariants

- A Task belongs to one Agent and carries the same Organization identity. The database enforces this with a composite foreign key to the Agent.
- A Task has a title, an optional description, and a status of `open`, `in_progress`, `done` or `failed`. It starts `open`, and its Agent may move it to any status.
- Task Notes are append-only and listed oldest first.
- Only the Task's own Agent writes: it creates Tasks, changes their status, adds Notes and attaches Files. The write methods take the Agent's Organization and id, which the caller has already authenticated, and refuse a deleted Agent or another Agent's Task with 404. People have no write path.
- People read Tasks with `task.read`, which every locked Agent Access Role grants. Reads filter by Agent visibility in the query: one Agent's Tasks, one Task with its Notes and File metadata, a download link for one File, or every Task across the Organization the reader can see. Lists are newest first and can be filtered by Agent and status; an Agent the reader cannot see simply yields no Tasks. An Agent the reader cannot see returns 404; one they can see without `task.read` returns 403. See [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md).

## Task Files

- A Task File is an Artifact the Agent has published, attached by id. `agent_task_file` holds the Artifact id and copies its name, content type and size; the bytes stay in the Agent's Artifact bucket. Artifacts never change once published, so the copies cannot drift. Name and type were validated when the Artifact was created.
- `attach_file` accepts only a `READY` Artifact of the same Agent and Organization; anything else is 404. Attaching the same Artifact to the same Task again returns the existing File. One Artifact may be attached to several Tasks.
- Each File pins its Artifact (`ArtifactService.pin`, kind `task`, owner the File's id) in the same transaction that records it, so the Artifact does not expire or get deleted by hand while the Task has it. Pinning takes the Artifact's row lock, which also serialises two attaches of the same Artifact.
- A File's Organization is always its Task's: a composite foreign key enforces it.
- `file_link` checks the reader's `task.read` access to the Agent, then returns `ArtifactService.link` for the File's Artifact: a short-lived signed download that the Artifacts download route serves.
- The size limit is the Artifact limit (`ARTIFACT_MAX_BYTES`). There is no per-Organization limit on Task Files.
- Without Artifact storage, the Agent cannot publish files, so it can still keep Tasks and Notes but attaches nothing.

## Deletion

Agent deletion is a soft delete, so the Agent foreign key never cascades. The deletion transaction in `AgentRepository.soft_delete_with_event` calls `stage_agent_task_cleanup` (`../api/domains/agent_tasks/cleanup.py`), which deletes the Agent's Tasks; their Notes and Files follow by cascade. The pins those Files held are not released: the Artifacts purge removes a deleted Agent's Artifacts whether or not they are pinned. If the deletion rolls back, the Tasks stay. Agent writes hold the Agent row `FOR KEY SHARE`, which conflicts with the deletion's `FOR UPDATE` but not with ordinary Agent updates, so no Task or File can be added after the cleanup ran.
