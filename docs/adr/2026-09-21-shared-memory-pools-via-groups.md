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
- **Distinct identities.** Each Agent keeps a distinct Honcho peer so contributions stay attributable. OpenClaw needed an explicit agent entry to stop every Agent being `agent-main` (`agents.list`, workspace/agentDir pinned to today's defaults so opting in never relocates files); Hermes already had `agent-<name>`. Both runtimes now use `agent-<agent id>` (the stable id, not the name) so a rename never orphans memory and Honcho never renormalizes the peer.
- **One human peer per pool (`owner`).** Both runtimes represent the person as a single `owner` peer (OpenClaw hardcodes `OWNER_ID`; Hermes was unified from `operator` to match). This is deliberate: memory is pool-scoped, not per-end-user (see *Per-user memory (deferred)*).
- **Recall is pool-wide, per runtime.** OpenClaw runs a first-party `honcho-pool-recall` plugin that queries the workspace-level dialectic; Hermes's baked-in `_chat_once` is patched to the same workspace-level query. Both verified live: an Agent surfaces a fact a *different* Agent in its pool learned. The stock OpenClaw plugin keeps **capture** but its **own recall is disabled** (via `allowPromptInjection: false`) — it was a redundant per-participant own-view read (`session.context`), not a second dialectic, so disabling it leaves our single pool-wide dialectic as the one recall per turn. The recall query is a recent-conversation window, not just the last message.
- **Cost is pool-level, measured per group.** Honcho holds one credential for all memory work, so LiteLLM's figure for that key is the memory total. AF-280-v2 apportions that total across pools by each workspace's token share (reconciling to the total) and reports a per-group figure — not split per Agent. Enforcing that cost against a budget is a separate, deferred decision recorded in *Enforcing per-pool cost* below.
- **Delete safety.** A per-Agent purge never touches a pool workspace, so deleting one Agent can never erase a pool shared by others. Deleting a *group* is the one sanctioned path to erase a pool (`delete_pool_workspace`), and it runs under a **retried domain-event delivery**, not a single best-effort pass: Honcho 409s a workspace delete while its async session deletes are still landing (the common case), so a one-shot delete would leave the pool's conclusions orphaned and unreachable. The retry drives it to completion; group membership drops via the FK.
- **Permissions.** Managing groups (create/rename/delete, assign Agents) takes a new org-scoped `memory_group.manage`, granted to org owners and admins. The same permission gates the **pool-wide** memory surface (see *Access control for the memory surface*).

## Tenant isolation (workspace-scoped tokens)

One Honcho instance holds every org's pool workspaces, and Agent pods reach Honcho directly (recall + capture). Left unauthenticated — as the first cut was — any pod (or a prompt-injected one running `exec`) could `POST /v3/workspaces/list` and read/write/delete **every org's** pool, breaking tenant isolation. A NetworkPolicy does not fix this: Agents legitimately need Honcho access, so once any Agent can reach an unauthenticated Honcho it can reach any workspace.

The fix is **auth on, with per-workspace-scoped tokens**. Honcho `POST /v3/keys` mints a key scoped to a `workspace_id` (confirmed in v3). The API holds the admin key; at provisioning each Agent is issued a token scoped to *its* pool workspace, injected into its Honcho config and sent as a bearer on recall/capture, and re-minted when the Agent changes pools (its workspace changes). Workspace-scope is the right boundary — an Agent needs every peer in its own pool (for pool-wide recall) and nothing outside it. Network reachability no longer implies data access.

## Access control for the memory surface

Pool memory is derived from **several** Agents' conversations, so exposing it through a single Agent's access would reveal (and let an Editor rewrite) memory derived from Agents the caller cannot see — contradicting the RBAC brief (no subordinate resource of an inaccessible Agent may be revealed). Resolution:

- **Pool-wide** view *and* curation (`scope=pool`, forget, correct) require `memory_group.manage` — the same bar the group memory page already enforced.
- Plain agent access (`agent.memory.read`/`agent.memory.manage`) is limited to **`scope=mine`**: only what *this* Agent contributed. The "Whole group" toggle is shown only to managers.

This keeps runtime sharing between Agents unchanged (that is the feature); it only aligns who can view/curate the pool through the management UI. The `require_action_allowing_deleted` path is dropped — its rationale (per-Agent workspace retained on delete) was v1; memory now lives in the pool, reachable via the group.

## Group size is bounded

Several pool operations are per-peer and therefore scale with the number of Agents in a pool: search fans out over `(observer, human)` collections (Honcho semantic search requires naming both peers — there is no search-all), recall retrieval likewise, and the facet counts. To keep these bounded and guarantee **complete** results (no silent truncation), group membership is capped at `MAX_MEMORY_GROUP_SIZE` (config, default **25**), enforced on add. If a pool ever genuinely needs to be larger, the escape hatch is a single shared-observer peer (pool reads become O(1)) at the cost of per-Agent `scope=mine` and attribution — deferred until a real need appears.

## Recall and search: shape, cost, and API limits

Honcho's memory API shaped several choices, verified live against 3.2.0 (the public docs are wrong on the first point):

- **Semantic search requires both `observer` and `observed`** (`conclusions/query` 422s otherwise); there is no search-across-everything. Facts are keyed `(observer, observed)`, and in these pools `observed` is always the human peer, so an Agent-wide search is `(each observer, human)` — linear in pool size, bounded by the group cap. The earlier silent `[:8]` peer cap is removed; a defensive ceiling reports *partial results* rather than ever truncating silently.
- **Pool-wide recall is only the workspace dialectic** (`POST /v3/workspaces/{ws}/chat`), which has **no observer/target** — it aggregates every peer and cannot be scoped to one person. This is why per-user recall isolation is not possible without replacing the dialectic (see *Per-user memory (deferred)*).
- **Cost.** The dialectic runs an LLM tool loop (~25s per call, measured); it dominates memory spend over the deriver. Recall is one such call per turn — our pool-wide dialectic. OpenClaw's stock recall (a `session.context` read, disabled here) was redundant with it, not a second dialectic.

## Per-user memory (deferred)

Every human collapses onto the single `owner` peer, so on a multi-sender surface (open Slack, Agent General Access) a fact one person shares can surface when another person talks — cross-user leakage within a pool. True per-user isolation is deferred: it needs per-sender peers **and** sender-scoped recall (which the workspace dialectic cannot do, so it means replacing the dialectic) **and** a cross-platform identity layer (the same human is a different id per platform, and none unifies them). The intended envelope for shared pools is therefore operator-run or trusted-shared-audience Agents; per-user memory is a follow-up if mutually-untrusted multi-user Agents become a target.

## Enforcing per-pool cost (deferred)

AF-280-v2 ships **measurement only**. Enforcement is deferred to [AF-338](https://aai-labs.atlassian.net/browse/AF-338); this section records the constraints and candidate design so they need not be re-derived.

The problem is that memory spend is invisible to the org LLM budget. AF-303 (`OrganizationLlmBudgetService`, on staging) caps an org by enrolling its Agent keys into a LiteLLM **team** (`team_id = organization_id`) and setting the team `max_budget`; LiteLLM enforces that in the request path, and a `reconcile_llm_budgets` CronJob pushes the stored budget onto the team while `check_llm_budget_thresholds` snapshots team spend and fires alerts. But **memory model calls run on Honcho's single LiteLLM credential, which is in no team**, so team budgets neither see nor cap them. Honcho's outbound request also carries **no org/workspace identity** (`user=""`, no tags, `team_id=null`, confirmed live), so LiteLLM cannot attribute or cap memory per org at request time either.

**Chosen approach — soft enforcement by reducing the budget, not raising the spend.** LiteLLM has no supported way to write a *team's* spend ([#30783](https://github.com/BerriAI/litellm/issues/30783)), and a synthetic per-org "memory" key's manually-set spend does not roll into team spend (team spend accrues at call time, from real calls on enrolled keys). So instead of trying to add memory to the spend side, the ceiling drops by the memory amount: `apply_team_budget(team, org_limit − apportioned_memory_spend)`. LiteLLM's native request-path enforcement then trips at `agent_spend ≥ limit − memory`, i.e. `agent + memory ≥ limit` — the same crossing point, written on the side LiteLLM lets us touch. The real Agent keys' spend stays LiteLLM's untouched source of truth.

That ceiling only binds Agent keys; the Honcho key keeps spending regardless, so enforcement is paired with a per-org **`memory_suspended`** state (folded into `memory_active`) that turns recall and formation off, cleared when the budget window renews.

Making that state bite on a **running** Agent is the open sub-decision, because there is no live server-side chokepoint for memory: an Agent pod calls Honcho directly (recall via `/v3/workspaces/{ws}/chat`, plus capture) using a `baseUrl` + workspace baked into its ConfigMap at provisioning, and memory config is only re-read on a restart (`strategy: Recreate`). Our ingest service and the in-pod healthz proxy carry tool-call telemetry and LLM traffic, not Honcho memory. So flipping the flag alone stops a *running* Agent's memory only on its next start — and a blocked-LLM Agent that still receives inbound messages keeps firing recall and formation on the Honcho key. Two ways to make suspension take effect promptly, to weigh in the follow-up:

- **Reprovision the org's running Agents** so they restart with memory off (the existing memory-off config path; memory lives in Honcho, so nothing is lost). A scheduled job restarting customer Agents is the cost — tolerable while those Agents are already LLM-blocked.
- **Patch our Honcho image** to refuse a suspended org's workspaces server-side. Heavier (a fork to carry), but it converges with the hard-enforcement patch below and needs no restart.

A standalone Honcho proxy was considered and dropped — hot-path infrastructure that the image patch does more cleanly.

**A dedicated CronJob owns enforcement.** Both actions — pushing the adjusted ceiling and flipping `memory_suspended` — depend on the same input (current apportioned memory spend per org), and both are state changes driven by measured spend. That does not belong on either AF-303 job: the alerts pass is informational by contract ("the proxy enforces the limit in the request path"), and the reconciler exists to repair budget *drift* and reads no spend. Overloading either blurs a single-purpose job. Enforcement gets its **own** CronJob — mirroring how AF-303 already keeps *reconcile* and *alert* separate — that reads memory spend once, computes each org's combined total, pushes the adjusted ceiling, and flips the flag. Its schedule is the leak knob (a tight interval bounds overshoot; it runs under `concurrencyPolicy: Forbid` like the others, so the interval must stay above the pass's own runtime).

**Display stays honest.** The org budget surface reads the stored `llm_budget_usd` (the true limit) and `llm_spend_usd` (an agent-spend snapshot written by AF-303's alert pass). The reduced ceiling lives only in LiteLLM, for enforcement — never shown. The enforcement job records the apportioned memory figure alongside it, and the surface sums the two, so the user sees "spent (agents + memory) of (true limit)" without either writer overwriting the other's number.

**Properties and limits.** Soft by construction. Overshoot on the Agent side is bounded by the enforcement job's interval; on the memory side the leak runs until suspension actually takes effect — the job's interval if Agents are reprovisioned or Honcho is patched, otherwise not until each Agent's next start — plus in-flight deriver work draining in Honcho. The effective ceiling ratchets down through the window as memory accrues. Apportionment is by token share, not exact per-call price — within tolerance for a budget, not billing-grade.

Alternatives considered and rejected:

- **Rely on the org team budget alone** — rejected. Memory is on the Honcho key, in no team, so the team budget caps Agents while memory keeps spending uncapped. Blocking an Agent's key does not reliably stop its memory: recall fires pre-LLM (`before_prompt_build` / the dialectic prefetch) and the deriver runs server-side on the Honcho key, both independent of the Agent's key.
- **Add memory to the spend side** (increment a team's spend, or a synthetic memory key whose spend rolls up) — rejected. No supported team-spend write ([#30783](https://github.com/BerriAI/litellm/issues/30783)), and set-key-spend does not propagate to team spend. Reducing the budget reaches the identical crossing point with no unsupported write.
- **Hard, request-time cap on memory** — deferred, not chosen. It needs org/workspace identity on Honcho's LiteLLM request so a LiteLLM tag/end-user budget can gate it. Upstream request-tagging is not an option, so the only path is patching our own Honcho image to inject identity (the hermes-base pattern) — a fork to carry. Revisit only if a per-org memory cap must be a hard guarantee rather than a bounded overshoot.
