# Agent tasks are a native store, with files kept as Artifacts

Status: Accepted
Date: 2026-10-21 (files revised 2026-10-28)
Origin: MDP-45 and AF-411, decided with the maintainer after the tracker spike; evidence in [`../evidence/mdp-45-tracker-spike/FINDINGS.md`](../evidence/mdp-45-tracker-spike/FINDINGS.md)

Agent tasks and their notes live in our own tables in the application Postgres, not in a self-hosted tracker. Vikunja passed every flow in the spike, but it would only have replaced the task tables and file storage. The routes, permissions, Agent tooling and UI are ours either way, and running it would have meant keeping a second system in step with our Agents and Organizations.

## Decision

- **Own tables.** Tasks carry their Organization and Agent, so visibility follows `AgentAuthorization` and deletion happens in the same transaction as the Agent's soft delete.
- **Files are Artifacts.** An Agent publishes a file as an Artifact ([`../features/agent-artifacts.md`](../features/agent-artifacts.md)) and attaches it to a task by id. The task keeps a reference and the file's name, type and size; the bytes stay in the Agent's private bucket. Each attachment pins its Artifact, so it does not expire while the task has it.

## Considered alternatives

- **Headless Vikunja behind our API:** it passed the spike. Rejected because it needs two more stateful pods per environment (Vikunja and its own Postgres, following the one-Postgres-per-service pattern in `helmfile.yaml.gotmpl`), and because its projects, and optionally per-Agent bots and expiring tokens, must be provisioned and deleted in step with our Agents and Organizations, the same deferred-provisioning and reconciler work LiteLLM needs. It is also AGPL and open-core, so a fork would carry the network-use clause.
- **Kanboard and Forgejo:** failed the spike (see FINDINGS).
- **Files in Postgres, in chunks, with per-file and per-Organization limits:** the first version of this decision, made while there was no object storage. AF-415 then added Garage-backed Artifacts, with per-Agent buckets, signed downloads, retention and purge. Keeping a second file store beside it would duplicate all of that.

## Consequences

- Task files need Artifact storage. Where it is not configured, or not yet provisioned for an Agent, the Agent cannot publish files, so it records Tasks and Notes without them.
- A file's size limit is the Artifact limit (`ARTIFACT_MAX_BYTES`). There is no per-Organization limit on task files; one would belong to Artifacts, where it covers every file an Agent publishes.
- Deleting an Agent leaves its Artifacts to the Artifacts purge, which removes a deleted Agent's files whether or not they are pinned.
- There is no tracker feature set to fall back on: boards, task relations, webhooks and calendar sync are built only if needed.

## Revisit if

- The roadmap moves from tracking Agent work towards a full task tracker (boards, relations, webhooks, calendar sync).
