# AF-280 Honcho Memory Layer — change log

Status: Active
Epic: AF-280
Related context: [`../agents.md`](../agents.md), [`../costs.md`](../costs.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../../adr/2026-09-03-honcho-backed-agent-memory.md`](../../adr/2026-09-03-honcho-backed-agent-memory.md)

## Current state

- Delivered: the Honcho service charts, their Helmfile releases, an embedding route on LiteLLM, runtime wiring for both OpenClaw and Hermes behind a fleet-wide toggle that defaults to off, per-Agent memory cost attribution, explicit cross-Agent memory sharing, and erasure of an Agent's memory when it is deleted with carry-over offered first.
- In transition: with `HONCHO_ENABLED` unset nothing changes, and Agents already running keep file-backed memory until they are stopped and started once. The toggle is fleet-wide, so enabling it moves every OpenClaw Agent on its next restart rather than a chosen subset.
- Next: commit. Everything designed for this feature is built. The Organization-wide memory directory was built and then removed with the move back to erasing memory on deletion; it is preserved on `AF-280-org-memory-view-backup`.
- Blockers: none. Kubernetes mints Honcho's LiteLLM key itself; a local compose run still needs `HONCHO_LITELLM_KEY` and `HONCHO_ENABLED=true` in `.env`, since compose has no install hook.

## Changes

### 2026-09-07 — AF-280 — Costs page shows a true total

- Added the all-in figure the page was missing: "Total Spend" is now model plus memory, the headline card. The old model-only card is renamed "Model Spend", and "Memory Cost" is unchanged, so the three read Total = Model + Memory and the numbers visibly add up.
- This removes the disclaimer under the old card rather than needing it: "Total Spend" now means everything, which is what the label always implied. The table note that memory is separate from the per-row Cost column stays, since that table has no total column.
- No data change; the total is summed in the view from the two figures the API already returns.

### 2026-09-07 — AF-280 — Costs page names memory cost and states it is separate

- Renamed the "Memory" label to "Memory cost" on both the summary card and the agent-breakdown column, so it reads as spend rather than a memory count.
- Added the disclaimer that memory cost is not part of the Cost figure. Cost is the agent's own model spend (its LiteLLM key); memory cost is its share of Honcho's separate fleet credential, and the two are never summed in the data. On the current stack memory ($0.39) exceeds model spend ($0.29), so a reader who took "Total Spend" as everything would be low by more than half. The note is in two places — under Total Spend and above the table — since each shows the numbers side by side with nothing otherwise saying they are different pockets.
- No data change: `total_cost` and `memory_cost` were already computed and stored separately; this only makes the separation legible.

### 2026-09-07 — AF-280 — memory tab: peer filters instead of in-page groups

- Replaced the in-page grouping with filter chips. The tab was grouping each page's rows by peer and labelling the header with the per-page count, so the number changed as you paged and a group spanned pages. Chips now carry each peer's real total — Honcho filters and counts server-side — and selecting one scopes the query to that peer, so "Page 1 of 2" means page 1 of that peer alone.
- Scoped the whole view to the Agent as observer. Honcho stores each fact under the Agent's view of a person *and* that person's own derived self-model, which restated everything twice; showing only what the Agent concluded removes that duplication at the source rather than papering over it in the client.
- Facets live in their own cached query, not the paged response, so the chips stay put when a filter is active — an earlier cut dropped them on filter, stranding you with no way back to Everyone.
- Kept a per-page content collapse: sharing deliberately writes a fact under the self-model and each person so both runtimes' recall find it, so one fact can still appear more than once on the Everyone view. Collapsed rows act on every copy — forgetting or correcting hits all of them.
- Relabelled `owner` as "About you" (chip) / "about you" (row). It is you talking to the Agent through the app, not headless traffic; the old "From messages with no sender" was wrong.
- Fixed the bare 500 on sharing. Provenance recording ran outside the guard around the Honcho write, so a DB hiccup failed a share whose conclusion had already landed. It is now best-effort: the fact stays, the memory simply shows unbadged, and the failure is logged rather than raised. This is the class of the earlier `memtest-openclaw` 500s.
- Server: `list_conclusions` gained `observer`/`observed` filters and `GET …/memory` an `observed` query param; `MemoryPage` gained `facets`. Coverage: facet counting and ordering, the zero-count peer being dropped, filtered requests skipping the facet pass, and the provenance-failure degradation. 1707 tests pass; `check-api`, `check-ui`, `lint-ui` clean; verified live — chips 110/45/65, filtering to a peer narrows and paginates honestly, chips persist across filters.
- Not addressed, and now the most visible thing in the tab: the OpenClaw memory plugin records its own system prompt as facts ("owner instructs the agent to…"), which dominates a real Agent's list. The Facts-only heuristic catches some by wording, not by design. Still the largest open memory-quality issue.

### 2026-09-07 — AF-280 — bound how long a new memory takes to appear

- Cut the deriver's age backstop from Honcho's stock 1800s to 300s. The token gate stays at 4096, which is where the cost saving actually comes from.
- The problem this fixes was mine. Widening the batch gate assumed latency was free, on the reasoning that recent turns are already in the runtime's context window so memory only matters for a *later* session. That holds for recall and not for the Memory tab, which shows derived memory — so batching is precisely what someone watching that tab waits on. Told an Agent something and it took roughly 25 minutes to appear.
- Worse than slow, it was unpredictable. The timer is per session and runs from that session's oldest unprocessed message, so the wait is anywhere from zero to the full window depending on where a session's timer already sat. Measured on two Agents created minutes apart: 12 minutes on one, 25 on the other.
- A hypothesis worth recording as wrong: the difference looked like a runtime difference, with Hermes appearing to reach the token gate on its own because it sends large `<prior_memory_file>` payloads. Measuring it killed that — Hermes had ~716 tokens across 18 messages, OpenClaw ~3,744 across 24, and neither approaches 4096. Both were waiting on the age backstop; only the timers' phase differed.
- Ordinary chat never reaches a 4096-token gate — a short exchange is a few dozen tokens — so the backstop, not the gate, is what governs when memory appears in practice.
- Verified against the running stack: the deriver reports 300s in effect with the gate and dialectic settings unchanged. `helm template` renders it, and `check-api`, `check-ui`, `lint-ui` are clean.

### 2026-09-07 — AF-280 — the OpenClaw config now says which memory backend is in use

- `memory.backend` is emitted as `qmd` when Honcho holds the memory slot, and stays `builtin` otherwise. It was hardcoded to `builtin` regardless, so the config claimed file-backed memory while Honcho held the data.
- This is a clarity fix, not a behaviour fix: the plugin slot decides which backend runs, and an Agent with Honcho in the slot already ran on Honcho with `builtin` written here — confirmed by `openclaw status --json --all` on a live pod reporting `backend: qmd, provider: honcho-selfhosted` against the correct workspace. But the config is the first place anyone looks when memory seems wrong, and it was pointing at the wrong one.
- The value came from the runtime rather than a guess: `memory.backend` accepts exactly `"builtin"` and `"qmd"`, which the runtime states in its own validation error. `"plugin"` and `"none"` are rejected outright, so a plausible-looking edit here would have failed the config rather than degrading quietly.
- Existing Agents keep whatever is on their volume until they are recreated; the config persists on the PVC, so this reaches an Agent on its next rebuild rather than its next restart.
- Also seen while validating, and not addressed here: the runtime reports `plugins.allow` as a legacy key ("now gates bundled provider discovery by default"), suggesting `plugins.bundledDiscovery` should be set explicitly. That is a plausible contributor to the `firecrawl plugin install failed` line in Agent boot logs, which predates this work.

### 2026-09-07 — AF-280 — memory is erased with the Agent, and carried over first

- Reversed the retention decision: deleting an Agent now erases its Honcho workspace. Deletion already destroys the volume, the Secret and every other resource, and nothing in the product restores an Agent — the soft-deleted row is audit and cost history. Memory was the lone survivor of an otherwise total teardown, which is an inconsistency rather than a safeguard, and it was conversational content about real people held under no retention policy.
- Removed the Organization-wide memory directory, whose main justification was reaching a deleted Agent's memory. It is preserved on the `AF-280-org-memory-view-backup` branch rather than deleted outright.
- Reverted the Organization-role grant of `agent.memory.read` that the directory required. An org-wide grant with no caller is a silent widening of trust, and the exact-matrix RBAC test exists to stop exactly that.
- The purge runs as a retried delivery on `agent.deleted`, not inline. This matters: Honcho returns 409 on a workspace delete while any session remains — the normal state for an Agent that did any work, confirmed against a live workspace — and deleting sessions first does not settle it, because both deletes are accepted asynchronously (202) and the workspace delete can still race ahead. Inline, a lost race would have left memory in place behind a log line, with no view left in the product able to reach it. The first implementation here was inline and would have shipped exactly that failure.
- Added carry-over in the delete flow: the retire dialog offers to copy the Agent's memory into other Agents, does it before deleting, and aborts the deletion if the copy fails. Leaving this to ordinary sharing would not have been enough — sharing is one fact at a time and needs foresight at the moment people have least of it, since deletion is usually "this Agent is redundant" and the loss is noticed later. Bounded at 500 memories, with truncation reported before anything is destroyed.
- Verified live: carry-over of all 49 memories from one Agent to another over the authenticated route, each arriving badged with its origin, then removed again through the API — which also confirmed that forgetting a memory clears its provenance row. Separately, a workspace holding a session, a message and a conclusion was fully erased through the real client.
- Coverage: 1701 tests pass; `check-api`, `check-migrations`, `check-monitoring`, `check-ui`, `lint-ui` clean. Seven new tests cover the purge, its retry-on-failure, the disabled-backend case, session-before-workspace ordering, and carry-over's copy, truncation and permission behaviour.
- The handler-registry wiring test caught the new handler being named in the catalog with nothing registered behind it, exactly as intended.

### 2026-09-06 — AF-280 — Organization-wide memory directory

- Added a `Memory` page beside Costs, listing every Agent in the Organization with the size of its memory and a link into the per-Agent view. Deleted Agents are listed too, which is the point: their memory is deliberately retained, and this is the only route to it.
- A directory rather than a merged stream of every memory. Honcho keys each workspace by Agent and nothing reads across workspaces, so a combined list would query every Agent on every page and paginate across sources with no shared order. Counting is one cheap call per Agent, and the per-Agent view already reads well.
- An Agent whose workspace cannot be reached reports `null`, not `0`, and the page says so rather than showing a number: zero means "learned nothing", which is a different claim from "could not ask", and collapsing them invites reading an outage as an empty Agent. One unreachable Agent does not blank the others' counts.
- Gated to Owner and Admin like Costs, and for the same reason: it exposes every Agent at once, including ones the caller holds no individual grant on.
- Fixed a real gap this surfaced: `agent.memory.read` existed only as an Agent Access grant, never an Organization-role one, so `require_organization` on it could never pass — the endpoint returned 403 for everyone including Owners. `cost.read` is in both sets, which is why Costs worked. The exact-matrix RBAC test caught the widening and was updated deliberately rather than relaxed.
- Fixed a bug the unit tests could not see: `agent_type` is declared as an enum but stored in a `String` column, so SQLModel returns a plain `str` and `.value` raised. The mock carried the enum member and hid it; the mock now uses the string the database actually returns.
- Coverage: four new tests (deleted Agents listed, unreachable reported as unknown, one failure not blanking the rest, Organization-wide permission required). 1698 tests pass; `check-api`, `check-ui`, `lint-ui`, `check-migrations` clean; verified against the running stack — 158 memories across 2 Agents, matching Honcho's own totals.
- Note: the deleted-Agent row is covered by tests and by `find_all_for_org` (the same call Costs uses for live and deleted Agents), but no deleted Agent existed locally to photograph it.

### 2026-09-04 — AF-280 — Honcho's LiteLLM key is minted by the deployment

- The honcho chart now mints its own LiteLLM key in a pre-install/pre-upgrade hook and publishes it as the `honcho-litellm-key` Secret. `HONCHO_LITELLM_KEY` was previously `required` in the helmfile with nothing producing it, so every deploy carried a manual step and a deploy without it failed at render.
- One Secret, two names: `LLM_OPENAI_API_KEY` for Honcho itself and `HONCHO_LITELLM_KEY` for the API, which hashes the key to find Honcho's spend in LiteLLM's activity report. Both consumers read the same value, so they cannot drift apart — the failure mode that would otherwise report memory cost as zero while Honcho spends normally.
- Setting `HONCHO_LITELLM_KEY` still pins a specific key and skips the Job entirely; the key is then carried inline as before. Both paths are rendered and asserted: with the value unset the Job renders and the inline entry disappears, with it set the reverse.
- Modelled on the existing `agentbarn-api` litellm-key Job rather than invented: same hook weights, same delete-then-generate handling for LiteLLM's unique-alias rule, same in-namespace Secret write through the API server with the `agent-farm-user` service account. No cluster-scoped resources, as the cluster is shared.
- `agentbarn-api` now `needs` the honcho release. Not a runtime dependency — the API runs without Honcho — but without the ordering the API pod would start before the Secret exists and report no memory cost until its next restart. The envFrom is `optional: true` so a Honcho-less environment still starts.
- Compose is unchanged and still needs the value in `.env`: there is no install hook there. `.env.deploy.spec` says so rather than leaving the difference to be discovered.
- Charts bumped: honcho 0.2.0 → 0.3.0, agentbarn-api 0.7.13 → 0.8.0. `helmfile template` renders the full stack with `HONCHO_LITELLM_KEY` unset, which previously failed outright.

### 2026-09-04 — AF-280 — memory tuned down from Honcho's stock settings

- Pinned the `low` dialectic level to a single tool iteration. `low` is what a caller gets when it asks for nothing, and Honcho ships it at 5 iterations — more than `medium` (2) or `high` (4), so the name is actively misleading and we were on the second most expensive tier by accident.
- Measured, not assumed: six recall questions with known answers, run at `minimal` and at stock `low` against a live Agent. Both answered 6/6. `minimal` used 36% fewer input tokens (30,960 vs 48,593), 60% fewer output tokens (593 vs 1,484), and was 18% faster. The extra iterations bought hedging preamble — "Based on the conversation history, …" — not accuracy.
- Widened the deriver's batch gate from Honcho's 512/1024 tokens to 4096/4096. The stock gate is a few short turns, so the deriver ran near-constantly and recorded conversational trivia ("operator asked where the runbooks live") beside anything worth keeping. A larger window costs one call where the default spent several and gives the model enough context to tell those apart. The 30-minute age flush is unchanged, so a quiet conversation is still derived rather than sitting unprocessed.
- Batching lag is not a real cost to recall: the current conversation's turns are already in the runtime's own context window, so memory is what an Agent recalls in a *later* session.
- Where the money actually goes, from Honcho's own telemetry: `dialectic.answer` accounted for 213,751 input tokens against the deriver's 14,204. Recall is roughly 15× writing, so tuning storage alone would have addressed the smaller half — which is why the dialectic change is the one that matters.
- Both settings are in the chart (`dialectic.lowMaxToolIterations`, `deriver.batch*`) and the compose config, which are separate files that drift independently. `helm template` renders; the running stack reports all four values in effect and answered 6/6 afterwards.
- Not covered: every test question was a single-hop lookup. Multi-hop questions ("what does their deploy schedule imply about on-call?") may genuinely need more iterations, and this result says nothing about those.

### 2026-09-04 — AF-280 — user-facing copy stops describing the implementation

- Rewrote copy across the Memory tab, the share dialog, and the Costs memory card that explained how the system works rather than what the user is looking at. The worst was the Costs card reading "Billed on one shared credential, split by measured token share" — an accurate description of the cost-attribution design and of no use to anyone reading a spend figure. It now reads "What your agents spent remembering things".
- Also removed: the vendor name from a load error, "Unattributed — no sender identity" as a group heading, "re-recorded as stated, not inferred" under the edit box, and the share dialog's assurance that destinations "are not given access to this agent's memory" — a sentence that answers an isolation question no user had asked.
- Group headings now say what the group is rather than naming the peer model: "About operator", "What <agent> knows", "From messages with no sender".
- The rule this violated: internal vocabulary (peers, observers, conclusions, credentials, token shares) belongs in code comments and these docs, never in the interface. It is documented here because the same words were used consistently enough to look deliberate.

### 2026-09-04 — AF-280 — memory tab rebuilt

- Reworked the Memory tab's information design. The old structure nested a bordered row inside a Card per group; it is now one bordered surface per peer with divided rows, which is both flatter and denser.
- Fixed a defect that read as a rendering bug: Honcho stores each fact once per (observer, observed) pair, so the same sentence appeared twice in one group. Identical content now collapses to a single row, and because a hidden copy would leave Forget deleting one of two identical rows, the row acts on every copy it stands for — Forget removes all, Edit corrects all. On the test agent this cut the page from 5151px to 3016px and the largest group from 44 rows to 23.
- The origin chip now appears only when it says something. Every row previously carried an identical grey "Stated" chip — 46 of 48 — which buried the two that differed. Only shared and inferred memories are chipped now; a shared one renders in the accent tone and is the only chip on a typical page.
- Added a Facts-only filter. Honcho derives a conclusion from every message including ones that only record that something was asked, and on this agent those outnumber real knowledge; the filter sets them aside by wording, hides rather than deletes, and says how many it set aside.
- Row actions moved to icons revealed on hover, using opacity rather than visibility so they stay in the tab order and appear on keyboard focus.
- Also: search gained an icon and a clear control, the share dialog gained agent avatars and a filter, empty states now teach rather than state, loading uses row skeletons, and the page/total count mismatch is resolved by saying "Showing N of M".
- Verified against the running stack at both 1440px and 390px, including hover state. `check-ui`, `lint-ui`, and the design detector are clean.
- Closed the gap noted in the previous entry: sharing was exercised over the full authenticated HTTP path, and `sharedFrom` came back as `memtest-openclaw` on the destination Agent's memory.

### 2026-09-04 — AF-280 — sharing in the app, and shared memories that admit where they came from

- Added: a Share action on each memory in the Agent's Memory tab. It opens the fact for editing, lists the Organization's other Agents, and reports per destination — one Agent failing does not hide another succeeding, matching what the API already returned.
- Added: `shared_memory_fact` records which Agent a memory was shared from, and the memory view now reads "Shared by <agent>" instead of the level. This closes a real defect rather than adding polish: a shared fact lands on the destination's own self-model, so before this it displayed as "<agent> (about itself)" — presenting a fact the Agent was handed as one it reasoned its way to.
- Why our side: Honcho's `ConclusionCreate` accepts content and a peer pair and nothing else, so there is nowhere in Honcho to record an origin. The row is keyed by conclusion id and joined back on read, scoped to the page being displayed rather than the whole Agent.
- Correcting a shared memory keeps the badge. Honcho has no update, so a correction deletes and recreates with a new id; the provenance row follows it, otherwise editing a shared fact's wording would silently make it look self-derived.
- Deletion: `target_agent_id` cascades (the memory is gone with the Agent, so the row explains nothing), `source_agent_id` nulls (the destination still holds the memory — "shared by a deleted agent" beats reverting to "figured this out itself"). Agents are soft-deleted, so in the normal case both survive.
- Removed: the `shared-memory` peer label in the memory view, dead since sharing stopped writing that peer.
- Coverage: 1694 tests pass, `check-api`/`check-ui`/`lint-ui` clean. Five new tests cover recording, not recording when Honcho rejects the write, the badge, cleanup on forget, and carry-forward on correct; the SQL itself was exercised against the real database, since the unit tests mock the repository away.
- Verified end-to-end over HTTP on 2026-09-04: sharing through the authenticated route returned `shared: true`, and the destination Agent's memory came back carrying `sharedFrom: memtest-openclaw`.

### 2026-09-04 — AF-280 — sharing actually reaches the destination Agent

- Fixed: a shared fact now surfaces in the destination Agent's own recall. Verified live — a Hermes Agent answered a question about incident postmortems from a fact it was never told, shared to it through the API from another Agent.
- Root cause: the previous implementation posted a message from a synthetic `shared-memory` peer into a separate session. Honcho stored it and reasoned over it correctly — its dialectic answered the question perfectly — but the runtime's own recall never looked there, so the feature returned 200 while doing nothing observable.
- Decision: shared facts are written as conclusions directly onto the destination's self-model, with both sides of the (observer, observed) pair being its AI peer. What the live tests established is narrower than it first appeared: a message from a synthetic peer is never recalled, while a conclusion is — but **both** conclusion placements recall equally well. An earlier reading credited the self-model with cleaner answers; that comparison was confounded, because the user-peer test used content contradicting an existing memory and the self-model test did not. Re-tested with non-conflicting content, the user-peer pair answered just as cleanly, and the earlier hedging was the Agent correctly surfacing a conflict. Self-model is therefore chosen on semantic grounds — shared knowledge is something the Agent knows rather than something it observed about a person — and because it avoids guessing a user peer name that differs per runtime and per message sender, not because recall is better.
- Confirmed: Honcho has no native cross-workspace sharing and is not going to grow one. `workspace_name` participates in nearly every composite foreign key, so isolation is structural rather than policy. Copying into the destination is the only mechanism available, not a shortcut past a better one; `clone-session` is within-workspace only.
- Note: provenance is not preserved in the stored memory. `ConclusionCreate` accepts no metadata, so a shared fact is indistinguishable from one the Agent concluded itself once written; the audit trail lives in the API call, not the memory item.
- Note: applying this locally required running the new permissions migration first — the runtime seeder cannot insert catalogue rows against the immutability trigger, so the API refuses to start until migrated. The API chart runs Alembic as a pre-install hook, so deployments are unaffected.
- Coverage: a test pins that sharing targets the destination's self-model rather than a synthetic peer, since that is the property a refactor would silently break. 1689 tests pass; `check-api` clean.

### 2026-09-04 — AF-280 — dedicated memory permissions, and deleted Agents' memory

- Delivered: `agent.memory.read` and `agent.memory.manage` replace `agent.read`/`agent.update` on every memory endpoint, including the destination check when sharing. Viewer holds read, Editor holds manage.
- Decision: memory got its own permissions for the same reason secrets did. It holds derived conclusions about real people, and rewriting it changes what an Agent believes rather than how it is configured — folding that into `agent.update` would mean anyone who can rename an Agent can also rewrite its beliefs. Viewer reads memory because it already reads the conversations memory is derived from; Editor manages it because it already holds `agent.secret.manage`, so it is no widening of trust.
- Delivered: a deleted Agent's memory is reachable again. Retention keeps the workspace, but every memory endpoint resolved through an active-only lookup, so retained memory was personal data nobody could view, search, or erase through the product.
- Decision: reaching a deleted Agent requires organization-wide visibility via the existing `get_deleted_in_scope` seam. A deleted Agent has no live access assignments, so per-agent grants cannot be evaluated against it; organization Owners and Admins are the only holders of that visibility, making the bar higher than the per-agent permission rather than lower.
- Note: the permission catalogue is locked at the database level — a trigger on `permissions` raises "Permission catalogue cannot be changed" on any write, with a matching one on system role grants. Permissions can therefore only be added by a migration that lifts the locks and restores them, which is what the new migration does. The runtime seeder is effectively a validator on a migrated database, not a writer.
- Coverage: five places pinned the old catalogue (the RBAC migration, `_AGENT_ACTION_PERMISSIONS`, the UI permission enum, and three test suites) and are now consistent. 1688 tests pass; `check-api`, `check-migrations`, `check-ui`, `lint-ui` clean.

### 2026-09-04 — AF-280 — memory moved into the Agent detail tabs

- Changed: memory is a **tab** on the Agent detail page rather than a standalone `/agents/{id}/memory` route. The standalone route, its wrapper component, and the toolbar link are removed.
- Decision: this follows the existing split rather than inventing one. Every data view of an Agent — conversations, tool calls, logs, work — is a URL-driven tab on the detail page; `/configuration` is a separate route because it is an editing surface. Memory is a data view, so it belongs with the tabs.
- Note: the first revision shipped it as a separate route with no navigation entry at all, so the page was reachable only by typing the URL. The tab both fixes reachability and matches convention.

### 2026-09-04 — AF-280 — memory cost surfaced in the UI

- Delivered: memory spend is now visible. A "Memory" tile on the costs dashboard shows the Organization's total, and the per-Agent table gains a Memory column.
- Fixed: the API had returned `memoryCost` and `totalMemoryCost` since the attribution slice, but the costs zod schema did not declare them, so zod stripped both and the numbers were silently discarded before reaching the page.
- Decision: memory spend is shown beside runtime spend rather than folded into `totalCost`. It is not billed on the Agent's own LiteLLM key — Honcho bills one fleet-wide credential — so adding it to a per-key total would misrepresent what that key spent. The tile says so: "billed on one shared credential, split by measured token share".
- Decision: an Agent with no memory spend shows "—" rather than "$0.00000", so a fleet with memory disabled does not read as a fleet that spent nothing on it.
- Coverage: verified against the live stack; the endpoint returns `totalMemoryCost` 0.0609 split across the two Agents. 1684 tests pass; `check-api`, `check-ui`, `lint-ui` clean.

### 2026-09-04 — AF-280 — memory search

- Delivered: `GET /agents/{id}/memory/search?q=` (`agent.read`) and a search box on the Memory page. Semantic rather than keyword — "what tools or languages does this person like" returns "owner's favorite programming language is Rust" with no shared words.
- Decision: search fans out across peer pairs and merges. Honcho stores conclusion vectors per (observer, observed) collection and rejects a query that does not name both peers, so no index spans an Agent's whole memory.
- Decision: the fan-out is capped at 8 peers. It is quadratic in peer count and peers grow with the number of people an Agent talks to; unbounded, a search box becomes a scan over every pair that ever existed.
- Coverage: three tests over the fan-out, deduplication across pairs, the cap, and read-only permission. 1684 tests pass; `check-api`, `check-ui`, `lint-ui` clean.
- Note: an earlier revision of this slice wrote this changelog's contents into `docs/features/agents.md` through a variable slip. Both files were restored from the copies on disk and git; no content was lost.

### 2026-09-04 — AF-280 — per-Agent memory view

- Delivered: an owner can see what an Agent has learned, correct it, and forget it. `GET /agents/{id}/memory` (paginated, `agent.read`), `DELETE .../memory/{id}` and `PUT .../memory/{id}` (both `agent.update`), plus a Memory tab on the Agent detail page, grouped by the peer each memory is about.
- Decision: the (observer, observed) pair is surfaced rather than flattened. Memory is stored per pair, so a flat list would misrepresent whose memory an item is; the page groups by the observed peer because "what does it think it knows about me" is the question an owner actually has.
- Decision: `owner` is rendered as "Unattributed (no sender identity)" rather than as a person. It is the plugin's bucket for messages arriving without sender metadata — cron runs, heartbeats, direct API calls — and labelling it as a user would be actively misleading.
- Decision: editing is a replace, not an amend, and the UI says so. Honcho exposes no update endpoint, so a correction deletes and recreates: the item gets a new id, and the replacement is always `explicit` because create cannot set a level. A corrected inference therefore stops being labelled an inference — surfaced rather than hidden behind an "edit" button.
- Verified live against a running Agent: listed 110 memories with pairs intact, corrected one (200, new id, level `explicit`), and forgot it (204).
- Coverage: seven service tests over the pair surviving to the caller, an Agent that has never conversed reading as empty rather than erroring, read vs update permissions, a correction preserving its peer pair, a 404 rather than a silent create, Honcho being unreachable surfacing as 502, and the disabled short-circuit. 1681 tests pass; `check-api`, `check-ui`, and `lint-ui` clean.
- Note: the UI camelCases responses through `humps`, which resolves the snake/camel inconsistency flagged during the cost work — it was never a defect.

### 2026-09-03 — AF-280 — cost attribution and sharing verified live

- Delivered: the last two unverified paths now have runtime evidence. Per-Agent memory cost reconciles exactly to LiteLLM's spend on the Honcho key, and an explicit shared fact lands in the destination Agent's workspace.
- Verified: 42 usage events captured from Honcho's CloudEvents telemetry, attributed per workspace and split by event type; `totalMemoryCost` equals the Honcho key's LiteLLM spend to the cent, divided by measured token share across the two Agents. Sharing created the `shared-memory` peer and session in the destination workspace with the promoted content.
- Fixed: the cost window excluded its own end date. `_date_range()` returns a calendar day, and parsing it bare gives midnight, so every event later that day fell outside the window — on a live system that is all of today's usage, and every share read zero despite the tokens being recorded.
- Fixed: `HonchoClient` took an optional `transport` on its constructor as a test seam, and injector resolved that annotation by handing in a bare `httpx.BaseTransport`, whose `handle_request` raises on first use. Unit tests always passed an explicit transport, so only the production path was broken. The seam moved to the method and the class now matches `LiteLLMClient`'s shape.
- Coverage: 1674 tests pass; a regression test pins that usage on the end date itself is counted.

### 2026-09-03 — AF-280 — live verification on both runtimes

- Delivered: Honcho memory verified end to end against running Agents on **both** runtimes. OpenClaw and Hermes each captured a conversation into their own workspace, and an OpenClaw Agent recalled a fact stored in an earlier session across pod restarts.
- Verified: workspace `af-<agent id>` created per Agent; peers `[owner, agent-main]` for OpenClaw and `[operator, agent-<name>]` for Hermes, confirming both AI-peer naming conventions; `honcho.json` resolved from `$HERMES_HOME`; the peer map on the PVC; embeddings routed through LiteLLM to OpenRouter at 1536 dimensions.
- Fixed (seven defects, none caught by the test suite): LiteLLM's default `encoding_format` is rejected by OpenRouter, so embeddings 400'd; the Honcho Postgres volume was mounted at the pg16 path and crash-looped on pg18; a required `HONCHO_LITELLM_KEY` broke every `docker compose` command because interpolation ignores profiles; `openclaw plugins install` deadlocked because the config named the plugin before it existed, which also silently broke the pre-existing Firecrawl install; `hooks.allowConversationAccess` was missing so nothing was ever captured; `HONCHO_ENABLED` was not passed into the API container; and Hermes needs `memory.provider` set — writing `honcho.json` alone left it reporting "Provider: (none — built-in only)".
- Fixed: recall timed out every turn. A dialectic query is an LLM call with a tool loop, measured at ~25s against a real workspace, against the runtime's 15s hook default — capture worked while recall silently never arrived. The hook timeout is now set explicitly on the plugin entry.
- Fixed: a failed plugin left the Agent with no memory backend at all, worse than the file-backed memory Honcho replaces. `memory-core` stays permitted in `plugins.allow` (inactive, no entry) and `start.sh` falls back to it when the plugin is genuinely missing.
- Fixed: the plugin lives on the PVC, so every restart after the first re-reported it as "install failed" when it was merely already present.
- Note: the Hermes defect is the reason `CLAUDE.md` now requires verifying features on both runtimes. It was invisible from the OpenClaw side — every OpenClaw check passed while Hermes ran built-in memory only.
- Coverage: 1673 tests pass; `check-api` and `check-migrations` clean.

### 2026-09-03 — AF-280 — explicit cross-Agent memory sharing

- Delivered: `POST /organizations/{organization_id}/agents/{agent_id}/memory/shared-facts` promotes operator-supplied content into one or more destination Agents' Honcho workspaces. The source Agent is audit context only — nothing is read out of its memory, the operator's own knowledge supplies the content — so this needed no read path into Honcho.
- Changed: `api/domains/agents/memory_sharing.py` (service, request/response models, `ai_peer_name_for_agent`), a route on the existing Agents router, and a narrow write-only `HonchoClient` (`get_or_create` peer and session, post message) in `api/infrastructure/honcho/client.py`. `docs/features/agents.md` gains a "Share memory" flow and source-map row; the ADR's summary, a new Consequences entry, and Revisit when are updated to match.
- Decision: chosen over an Org-scoped shared workspace with peer-level observe grants (the alternative discussed and rejected when this was scoped). Explicit promotion needed no rework of the just-built per-Agent workspace design, and keeps the RBAC surface exactly what it already is — two `AgentAuthorization` checks — rather than resting correctness on our own gating of a workspace where the raw data already commingles.
- Decision: authorization fails the whole call if any named destination is not visible or lacks `agent.update`, before any write happens, so a caller cannot learn whether an Agent they cannot see exists by getting a partial success. A Honcho-side failure on one destination is a different kind of failure and is reported per destination instead, so one unreachable workspace doesn't block writes that would otherwise succeed.
- Decision: the destination's own AI peer is added to the write, using the exact peer-naming convention each runtime already has — `agent-{agent.name}` for Hermes, matching `build_honcho_config`'s own `aiPeer` field exactly; `agent-main` for OpenClaw, fixed by Honcho's own OpenClaw integration docs together with every OpenClaw Agent's config naming its one logical agent "main" (`builders/openclaw.py`). Neither convention is invented here; both are read from what the builders already emit or from Honcho's own documented behaviour, per the standing rule against assuming OpenClaw/Hermes runtime behaviour.
- Decision: scoped to currently active Agents on both ends for this slice. Promoting *from* a deleted Agent's retained memory is the natural next step the retention reversal enables, but it needs deleted-Agent read authorization that `AgentAuthorization` does not have today — adding that is a bigger, separate decision (who may read a deleted Agent: Organization-level authority, Platform authority, or something narrower) and is left as a follow-up rather than folded in here.
- Coverage: six unit tests — the two AI-peer-naming conventions pinned exactly (a rename on either side would otherwise break silently until a live run), the Honcho-disabled short-circuit, fan-out to multiple destinations with per-destination peer names, one destination's Honcho failure not swallowing another's success, and an authorization failure aborting the whole call rather than partially succeeding.
- Open: whether a promoted fact is actually incorporated into the destination runtime's own recall (its `honcho_context` / `honcho_profile` tool calls) is unverified. The write follows Honcho's documented (observer, observed) mechanism precisely, but confirming the runtime's own dialectic query surfaces it is only possible against a running Agent — the same category of open item as OpenClaw plugin resolution and Hermes's `honcho.json` discovery.

### 2026-09-03 — AF-280 — retention reversed, sharing scoped in

- Delivered: deleting an Agent no longer purges its Honcho workspace. Memory content is retained indefinitely, matching how the Agent's own row, audit history, and blocked-not-deleted LiteLLM key already survive deletion.
- Changed: removed `HonchoWorkspacePurgeHandler`, its `agent.honcho_workspace.purge` catalog registration and DI wiring, and its tests. `AGENT_DELETED` reverts to its original registration against only the security audit handler. `api/infrastructure/honcho/client.py` is trimmed to `workspace_id_for_agent`, the one piece still load-bearing (both runtime builders name a workspace from it); the HTTP purge client and its tests are removed as dead code rather than kept speculatively.
- Decision: reversed rather than left in place, because retaining a deleted Agent's memory is what makes reusing it — including sharing it with another Agent — possible at all. Purging on delete and sharing afterward are contradictory positions.
- Decision: retention is unbounded for now, with no expiry policy. This is conversational content about real people; the ADR now says explicitly that an unbounded default should be revisited before being relied on operationally, mirroring the existing audit-records retention ADR's stance.
- Scope change: cross-Agent sharing, previously excluded, is back in scope as a follow-up. Full workspace merging (AF-193's original ask) stays rejected for the RBAC reason already on record; what's wanted now is narrower — "some stuff," not everything — and the mechanism is not yet chosen.
- Coverage: full suite re-run after removal, 1661 passed (net -5 from the removed purge tests); `check-api` clean.

### 2026-09-03 — AF-280 — memory cost attribution

- Delivered: memory spend is attributed per Agent, and therefore per Organization. An Organization's cost summary now carries each Agent's memory cost and the Organization's memory total.
- Changed: `honcho_usage_event` table and migration, `HonchoUsageRepository`, `HonchoUsageService` in the costs domain, `POST /ingest/v1/honcho/usage` on the Ingest app, `memory_cost` on `AgentCostRead` and `totalMemoryCost` on the summary, Honcho telemetry configuration across chart and Compose, and `HONCHO_TELEMETRY_KEY` / `HONCHO_LITELLM_KEY` through Helmfile and `.env.deploy.spec`. API chart 0.7.13, Honcho chart 0.2.0.
- Correction: this reverses the earlier conclusion, recorded in the ADR, that per-Agent attribution was impossible. That was inferred from the request path alone — Honcho sends every call on one credential with no workspace identity, so LiteLLM genuinely cannot split it. What was never checked is that Honcho *emits* a per-call telemetry event naming the workspace and counting tokens. It does, and it covers both model and embedding calls.
- Decision: token counts are used only for the shares; the money is LiteLLM's authoritative spend on Honcho's key. That avoids maintaining a price table and guarantees the per-Agent figures reconcile to the real total. Apportioning by message volume stays rejected — this is measured, not estimated.
- Decision: `TELEMETRY_HIGH_VOLUME_SAMPLE_RATE` is pinned to 1.0 rather than left at its default. These events are sampled below 1.0, and Honcho's own docs warn that rebuilding per-call analytics from a sampled stream undercounts.
- Decision: Honcho holds a dedicated LiteLLM key, never the master key. An earlier revision let Compose fall back to the master key so a local run needed no setup; that key mints and revokes every other key, and its spend is not a per-key line any report reads, so the fallback forfeited both least privilege and the total the shares divide.
- Decision: usage from workspaces that are not Agents still counts toward the denominator. Excluding it would inflate every Agent's share of a bill they did not incur alone.
- Coverage: nine unit tests over parsing and attribution — unknown event types skipped rather than failing a batch carrying real usage, calls without a workspace dropped rather than pooled, single event as well as batch, missing token counts treated as zero, shares reconciling exactly to the spend, and non-Agent workspaces held in the denominator. The migration applies and reverses.
- Note: the UI is unchanged. `AgentCostRead` serializes snake_case while the UI's zod schema expects camelCase for those same nested fields, so the existing convention there needs confirming before adding a field to it.

### 2026-09-03 — AF-280 — local runnability

- Delivered: Honcho runs in the local stack, and the API and Agent pods each reach it by the name that resolves for them.
- Changed: `honcho_base_url` split into an API-side and an Agent-side setting, the API chart passing both, `honcho`/`honcho-deriver`/`honcho-db` added to `compose.yml` under the `k3d` profile, a local `docker/honcho/config.toml`, the embedding route added to `docker/litellm/config.yaml`, and Honcho values in `.env.deploy.spec`. API chart version 0.7.11.
- Fixed: a single Honcho base URL was used for both the API's purge client and the Agent's runtime config. In-cluster both resolve to the same Service so it worked, but locally the API runs in Compose while Agents run in k3d and reach Honcho through the host — the same split `agent_litellm_base_url` already exists for. A test pins the purge client to the API-side URL.
- Decision: local Honcho runs in Compose beside LiteLLM rather than in k3d, matching where the rest of the local stack lives, and binds all interfaces for the same reason LiteLLM does: agent pods reach the host through the bridge gateway rather than loopback.
- Note: `docker/litellm/config.yaml` and `helm/litellm/templates/configmap.yaml` are separate files carrying the same model list. The embedding route had to be added to both, and they drift independently.
- Coverage: `docker compose --profile k3d config` validates; the local `config.toml` parses and pins all five dialectic levels; `make check-api` passes.

### 2026-09-03 — AF-280 — Hermes wiring

- Delivered: a Hermes Agent takes Honcho as a memory provider on the same toggle and the same per-Agent workspace as OpenClaw, so the feature covers both runtimes rather than one.
- Changed: `build_honcho_config` and a `honcho_config` argument on the Hermes ConfigMap builder, `HERMES_HOME` on the Hermes Deployment, `scripts/hermes/start.sh` installing `honcho.json` beside `config.yaml`, and the service passing the provider config.
- Decision: Hermes runs Honcho *alongside* `MEMORY.md` and `USER.md` rather than replacing them, which is the opposite of OpenClaw's single memory slot. That asymmetry is the runtimes', not ours, and the ADR now states it rather than describing the OpenClaw case as if it were general.
- Decision: `HERMES_HOME` is set to the mounted state directory. Hermes resolves `honcho.json` from `$HERMES_HOME` before anything else; left unset it looks under the home directory, which is not the mount, and the provider config is silently never found — the same class of failure as the OpenClaw peer map.
- Coverage: Hermes builder unit tests cover the absent config, the generated provider config and its workspace, `HERMES_HOME` matching the state mount, and `start.sh` installing the file.

### 2026-09-03 — AF-280 — workspace lifecycle

- Delivered: deleting an Agent purges its Honcho workspace, as an `agent.deleted` Domain Event delivery.
- Changed: new `api/infrastructure/honcho` client, `HonchoWorkspacePurgeHandler` in the Agents domain, `agent.deleted` registered against the new handler alongside the security audit projection, and handler registration in the injector module.
- Decision: the purge runs on the delivery path rather than inline in `delete_agent`. Honcho returns 409 for a workspace that still holds an active session and offers no bulk session delete, so a purge is a paginated walk of sessions followed by the workspace. An Agent that did any work has active sessions, so an inline single-call delete would have failed in the normal case, not the rare one, and failed silently because that cleanup is non-blocking by design. Running it as a retried delivery also removes the need for the orphan reconciliation sweep that was previously a follow-up.
- Decision: an unreachable Honcho raises a retryable handler error rather than a terminal one; dead-lettering would leave the workspace behind with nothing left to notice it. The session walk is bounded, so an Agent with a pathological number of threads cannot hold a worker indefinitely.
- Coverage: unit tests cover the derived workspace name, the disabled no-op, retryable classification, and — against a mock transport — that every session is deleted before the workspace.
- Follow-up: nothing outstanding in the repository; remaining work is runtime verification and the deployment env keys.

### 2026-09-03 — AF-280 — OpenClaw wiring

- Delivered: an OpenClaw Agent takes Honcho as its memory backend when `HONCHO_ENABLED` is set, with a workspace derived from the Agent id (`af-<agent id>`).
- Changed: `builders/openclaw.py` swaps the memory slot, `agents/service.py` passes the workspace, `core/config.py` gains `honcho_enabled` and `honcho_base_url`, `scripts/openclaw/start.sh` installs the plugin, and the API chart carries the toggle (version 0.7.10).
- Decision: the plugin installs at runtime from `start.sh`, matching how the Firecrawl plugin is already installed, and the install is gated on the overlay naming `openclaw-honcho`. `openclaw plugins install` rewrites `plugins.slots.memory`, so an unconditional install would move every Agent off file-backed memory regardless of configuration.
- Decision: the Honcho peer map is pinned onto the Agent's volume. The plugin defaults it to `~/.honcho`, which is not the mount, where it is lost on every pod recreation and each participant silently becomes a new peer.
- Decision: the toggle is fleet-wide rather than per Agent. A per-Agent opt-in needs a settings surface and migration; the fleet flag defaults to off and is reversible by restarting an Agent, which keeps the rollout controllable without that work.
- Coverage: builder unit tests cover the default slot, the Honcho slot and its entry, the peer-map path against the volume mount, and the install gate. `make check-api` and `make check-migrations` pass; `helmfile template` renders the fleet at 67 manifests with the toggle both set and unset.
- Follow-up: recall verification against a running Agent, and workspace deletion on Agent delete.

### 2026-09-03 — AF-280 — embeddings

- Delivered: an optional OpenAI embedding route on LiteLLM, so Honcho has a provider to resolve `models.embedding` against.
- Changed: `helm/litellm` values, Secret, and ConfigMap, with its chart version bumped to 0.4.2; `OPENAI_API_KEY` passed through Helmfile with an empty default.
- Decision: embeddings route through OpenRouter on the existing credential, so the fleet still holds one provider key. OpenRouter serves embeddings at `/api/v1/embeddings` but does not list those models in `/models`, so the wildcard passthrough cannot reach them and the model is named explicitly in the LiteLLM model list. `openai/text-embedding-3-small` was chosen because its 1536 dimensions match what Honcho's vector store is fixed at, and that dimension cannot be changed once memory exists.
- Decision: embeddings are not optional in Honcho — `EMBED_MESSAGES=false` only disables message search, while `crud/representation.py` and `crud/document.py` embed regardless — so the service cannot run without this route.
- Correction: an earlier revision of this slice added a separate OpenAI provider credential, on the mistaken finding that OpenRouter had no embedding models. That was inferred from the `/models` catalogue alone, which lists only text-generation models; the endpoint exists and answers on the OpenRouter key. The extra credential has been removed.
- Decision: the model configuration stays a deploy-time value rather than a platform-admin setting. Making it runtime-editable would need a stable LiteLLM alias, `store_model_in_db`, and a platform settings surface that does not exist yet; the embedding model should stay static regardless, because changing it invalidates every stored representation without erroring.
- Coverage: five embedding models were called against the live OpenRouter endpoint to confirm availability and dimensions; `helmfile template` renders the fleet at 67 manifests with the embedding route present and no second provider credential anywhere in the output.

### 2026-09-03 — AF-280 — chart

- Delivered: `helm/honcho` (API and deriver Deployments, Service, config and env ConfigMaps, Secret) plus `postgres-honcho` and `honcho` Helmfile releases ordered after PostgreSQL, Redis, and LiteLLM.
- Changed: new chart, two Helmfile releases, and the runtime/deployment architecture doc. No API, UI, schema, or Agent runtime change; no existing chart's templates or values were touched, so no other chart version moves.
- Decision: model configuration is mounted as `config.toml` rather than passed as environment, because the dialectic reasoning levels are a dict field that does not express reliably through environment nesting, and every module must be pinned to LiteLLM explicitly — an unset module falls back to the provider's own endpoint and would send this deployment's LiteLLM key to the wrong host. Background dreaming is off by default. The API runs one replica because its entrypoint provisions the database on every start.
- Coverage: `helm template` renders the chart and its required-value guards; the rendered `config.toml` parses and pins all five dialectic levels, deriver, summary, embedding, and both dream models to LiteLLM; `helmfile template` renders the full fleet without regression and `postgres-honcho` resolves to `pgvector/pgvector:pg18`.
- Follow-up: an embedding route on LiteLLM, the deployment env keys, then OpenClaw builder wiring.

### 2026-09-03 — AF-280

- Delivered: the decision record for replacing the runtime memory slot with Honcho, scoped to one workspace per Agent.
- Changed: docs only — new ADR, this epic log, and its `docs/INDEX.md` route. No API, UI, schema, runtime, or deployment change.
- Decision: memory quality and platform-readable memory are the goal; cross-Agent sharing is out of scope, because the procedural half is already delivered by Organization-scoped Skills and the remaining half crosses the Agent Access boundary. Agent deletion purges the Agent's workspace inline, best-effort and non-blocking, consistent with existing PVC and Kubernetes resource cleanup; an orphan reconciliation sweep is deliberately deferred and its absence is recorded in the ADR.
- Verified: the published image runs its own database provisioning before the API starts, so the chart needs no migration hook, but the deriver entrypoint does not provision and the API must reach ready first. Workspace configuration carries reasoning, peer-card, summary, and dream settings only — no model credentials — and the model backends send no workspace identifier, so LiteLLM cannot attribute a call to an Agent. The webhook endpoint limit is per workspace and places no cap on the number of workspaces.
- Follow-up: chart and pgvector PostgreSQL release, then runtime builder wiring.
