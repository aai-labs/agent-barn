# Agent memory is shared in pools, opted into by group membership

Status: Accepted
Date: 2026-09-21
Origin: [AF-280](https://aai-labs.atlassian.net/browse/AF-280)
Supersedes: [2026-09-03 — Honcho backs Agent memory, scoped to one workspace per Agent](2026-09-03-honcho-backed-agent-memory.md)

The first design gave each Agent its own Honcho workspace and kept memory isolated per Agent, with cross-Agent sharing available only as an explicit operator-driven copy. The requirement changed: memory should be **opt-in per Agent** and opted-in Agents should **share** memory — distinct Agents that can see what the others have learned. This ADR records the shift from one-workspace-per-Agent to shared **memory pools**, where a **group** is the pool and **group membership is the opt-in**.

The whole memory mechanism now keys off a pool id rather than an Agent id: an Agent in a group uses the workspace `af-pool-<group id>`; an Agent in no group has no shared memory. Everything else — deriver instructions, cost, deletion — follows from that one change.

## Considered alternatives

- **Keep one workspace per Agent, share by copying conclusions** (the previous ADR) — rejected. Copying reaches recall but is a snapshot, not shared memory: later learning on the source does not propagate, and the operator must re-share. The requirement is live shared memory, which one workspace shared by several Agents gives directly.
- **Share by collapsing opted-in Agents onto one Honcho peer** (`agent-main` for all) — rejected despite being the cheapest path. It works with the stock plugin unchanged, but it throws away per-Agent attribution: you cannot tell which Agent learned a fact, and every Agent's self-model merges. Distinct peers per Agent were kept instead.
- **A per-org "house pool" that every opted-in Agent joins by default** — rejected in favour of explicit named groups. Groups subsume the house pool (a group is a named pool) and match the operator's mental model ("these Agents share"); a silent org-wide default is a blunter version of the same primitive. Cross-org pools stay rejected for the RBAC reason the first ADR recorded — a group is org-scoped.
- **Shared workspace alone makes memory shared** — disproven, then designed around. A live spike showed Honcho recall is per-`(observer, observed)`: dropping distinct Agents into one workspace does **not** make them see each other's memory through the runtimes' default (own-view) recall. The workspace-level dialectic (`POST /v3/workspaces/{ws}/chat`) *does* aggregate across peers. So shared recall is a deliberate recall change on each runtime, not a free consequence of a shared workspace.
- **Multiple groups per Agent** — rejected for now. An Agent runs one runtime with one memory workspace, so one group per Agent is the natural fit (a single FK). Many-to-many would mean multi-workspace writes and merged recall — a larger design deferred.
- **Migrate an Agent's prior file/isolated memory into its pool on join** — rejected, carrying the first ADR's reasoning forward: uploaded files produce representations that compete with what the deriver later infers. Joining a group is a cold start for shared memory.

## Consequences

- **Model.** A `memory_group` table (org-scoped, unique name per org); `agent.memory_group_id` is a nullable FK (`SET NULL` on group delete). `memory_active` = Honcho deployed **and** the Agent is in a group. The workspace is `af-pool-<group id>`.
- **Opt-in / opt-out.** Adding an Agent to a group turns its shared memory on; removing it turns it off on the Agent's next start. Opt-out only revokes access — the Agent's past contributions stay in the pool.
- **Distinct identities.** Each Agent keeps a distinct Honcho peer so contributions stay attributable. OpenClaw needed an explicit agent entry to stop every Agent being `agent-main` (`agents.list`, workspace/agentDir pinned to today's defaults so opting in never relocates files); Hermes already had `agent-<name>`.
- **Recall is pool-wide, per runtime.** OpenClaw runs a first-party `honcho-pool-recall` plugin that queries the workspace-level dialectic (the stock plugin still handles capture); Hermes's baked-in `_chat_once` is patched to the same workspace-level query. Both verified live: an Agent surfaces a fact a *different* Agent in its pool learned.
- **Cost is pool-level.** Honcho holds one credential for all memory work, so LiteLLM's figure for that key is the total — reported as one org-level number, not split per Agent.
- **Delete safety.** `delete_workspace` refuses a pool workspace, so deleting one Agent can never erase a pool shared by others. Deleting a *group* is the one sanctioned path to erase a pool (a deliberate `delete_pool_workspace`); it also drops members via the FK.
- **Permissions.** Managing groups (create/rename/delete, assign Agents) takes a new org-scoped `memory_group.manage`, granted to org owners and admins.
