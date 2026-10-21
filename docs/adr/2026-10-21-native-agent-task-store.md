# Agent tasks are a native store, with files in Postgres

Status: Accepted
Date: 2026-10-21
Origin: MDP-45 and AF-411, decided with the maintainer after the tracker spike; evidence in [`../evidence/mdp-45-tracker-spike/FINDINGS.md`](../evidence/mdp-45-tracker-spike/FINDINGS.md)

Agent tasks, their notes and the files Agents attach to them live in our own tables in the application Postgres, not in a self-hosted tracker. Vikunja passed every flow in the spike, but it would only have replaced the task tables and file storage. The routes, permissions, Agent tooling and UI are ours either way, and running it would have meant keeping a second system in step with our Agents and Organizations.

## Decision

- **Own tables.** Tasks carry their Organization and Agent, so visibility follows `AgentAuthorization` and deletion happens in the same transaction as the Agent's soft delete.
- **Files in Postgres.** Attachments are stored in chunks in the application database, with a per-file and a per-Organization limit. They sit behind a narrow storage interface so they can move to object storage later without touching tasks.

## Considered alternatives

- **Headless Vikunja behind our API:** it passed the spike. Rejected because it needs two more stateful pods per environment (Vikunja and its own Postgres, following the one-Postgres-per-service pattern in `helmfile.yaml.gotmpl`), and because its projects, and optionally per-Agent bots and expiring tokens, must be provisioned and deleted in step with our Agents and Organizations, the same deferred-provisioning and reconciler work LiteLLM needs. It is also AGPL and open-core, so a fork would carry the network-use clause.
- **Kanboard and Forgejo:** failed the spike (see FINDINGS).
- **Object storage for files now:** MinIO's community edition is no longer maintained, and choosing a replacement is not needed for v1 volumes.

## Consequences

- The application database grows with Agent files, bounded by the limits. Backups of `postgres-app` cover them.
- There is no tracker feature set to fall back on: boards, task relations, webhooks and calendar sync are built only if needed.

## Revisit if

- The roadmap moves from tracking Agent work towards a full task tracker (boards, relations, webhooks, calendar sync).
- File volume makes the application database uncomfortable to back up or restore. Move files behind the storage interface to object storage then.
