# Agent files sync two ways through the Sync Provider, with no provider token in the pod

Status: Accepted
Date: 2026-10-21
Origin: AF-384 ticket ("Two-way file sync"), and decisions taken with the maintainer while planning it

Once an Organization has an active Sync Provider Connection, each Agent gets its own folder inside "Agent Barn", and that folder is kept in sync both ways with the Agent's files. The ticket sets four constraints:

1. the provider's credentials never enter an Agent pod;
2. a separate Sync Engine does the provider work;
3. file contents move directly between the pod and the provider;
4. a disallowed change is undone by re-uploading the Agent's copy.

## Decision

- **No provider token in the pod.**
  - The pod asks Ingest, authenticated by its per-start ingest key, for one pre-authenticated upload or download URL per file.
  - The API and the Sync Engine hold the app-only token; the pod never does.
  - A pod-supplied item id is never trusted. The server re-reads the item from the provider before recording it.
- **A separate Sync Engine.** A Deployment runs one pass per active connection whose provider declares the file-sync capability. Each pass:
  - gives every live Agent a correctly named folder;
  - reads the provider's changes since its stored cursor;
  - turns those changes into operations for the pod, or into provider actions it can take alone, such as moving a file or renaming it back.

  Folders follow Agent creates, renames and deletes through this pass, not through a Domain Event handler. The maintainer chose one code path. The pass is scheduled work, so it falls under the RBAC brief's existing background-work exception rather than needing a new one.
- **Which files sync.**
  - The Agent's work and memory files sync both ways.
  - Files the start script rebuilds from the Template, and `skills/`, are mirrored read-only: a user's edit is undone.
  - Credentials and runtime machinery never leave the volume.
- **The Agent wins.**
  - A disallowed edit is undone by re-uploading the Agent's copy, which needs the pod. While the Agent is stopped, the undo waits for its next start.
  - A deleted file is re-uploaded the same way. A renamed file is renamed back by the engine.
  - When the user and the Agent change the same file before a sync, the Agent's version is uploaded over the user's, and an activity entry is recorded. The maintainer chose the provider's version history over the ticket's separate conflict-copy file, because the copy would be extra logic and storage for no added benefit.
- **Nothing in the provider deletes a file on the Agent's volume.** The in-pod helper has no delete path. An Agent deleting a file deletes it at the provider, which sends it to the recycle bin there.
- **Provider-neutral.**
  - Tables, routes and the engine are generic, keyed by connection and provider.
  - Provider calls go through a new `file_sync` plugin capability, as the [sync provider plugin seam](2026-10-16-sync-provider-plugin-seam.md) requires. OneDrive implements it first.

## Consequences

- **Every Organization Member can see the files.** The "Agent Barn" folder is open to every Organization Member at the provider. Members without Agent Access to an Agent can therefore read its synced files, and can edit its work and memory files, which the Agent then reads. The maintainer accepted this as a documented limit rather than mirroring Agent Access into provider permissions.
- **Disconnect deletes the Agent folders and keeps the root.** After the administrator's fresh sign-in is checked, disconnect deletes the Agent folders (to the provider's recycle bin) with Agent Barn's own access, then revokes that access with the sign-in. The "Agent Barn" root folder stays. If a step fails, the connection stays active and the engine re-creates the folders.
- **Running Agents pick sync up on restart.** Sync reaches an Agent at its next start, because the in-pod helper ships in the runtime ConfigMap. Running Agents report an available update, and none is restarted to start syncing.
