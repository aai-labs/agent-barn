# Playbooks — change log

Status: Active
Epic: Playbooks (no ticket yet)
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../activity-and-ingest.md`](../activity-and-ingest.md), [`../agent-memory.md`](../agent-memory.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../costs.md`](../costs.md)

Story: as a partner, I want to capture how I trained my best Agent and clone that training to new Agents automatically, so that the firm compounds its expertise instead of starting over each time. v1 extracts patterns from sessions, writes a playbook in Markdown, has a person review it, and installs it as a Skill. Compiling playbooks into Agent configuration comes later if the pattern proves valuable.

## Decisions

- The story predates the switch from Honcho to Hindsight. Extraction reads Conversation Messages and Tool Calls from PostgreSQL and the source Agent's long-term memories through the memory viewer. A Runtime's built-in memory and Hermes session storage on the Agent volume have no read API and are out of scope.
- Only Organization Owners and Admins extract: a run needs Agent `activity.read` on the source Agent and the Organization Permission `skill.manage`. No Permission catalogue change.
- The output is always an Organization Skill Draft that a person reviews and publishes. There are no Platform or cross-Organization playbooks.
- The extraction model is a Platform Administrator setting with a deployment default, like the Agent Memory model; Organization model allowlists do not apply.
- A run is billed to the source Agent's own LiteLLM key, so LiteLLM's existing Agent and Organization spend limits apply and the spend appears on that Agent's Costs tab.
- No Connection or session exclusions in v1.

## Current state

- Delivered: the decisions above and the glossary terms **Playbook** and **Playbook Extraction** in `CONTEXT.md`.
- Delivered: Playbook Extraction runs — the `playbook_extraction` table, start/list/detail/cancel APIs, the `playbook.extraction.requested` audit event, the `playbook_extraction` worker queue, and the worker's claim and authority re-check. The contract is [`../playbooks.md`](../playbooks.md).
- Delivered: session assembly and the preview endpoint, which reports what a run would read and an estimated transcript token count.
- Delivered: the Platform Playbook model setting with its audit event, and the LiteLLM completion client; the worker receives `LITELLM_BASE_URL`.
- Delivered: the pipeline — notes per conversation, the playbook step with long-term memories, the Skill Draft write, and usage recording.
- Delivered: the UI — the Agent Playbooks tab, run history, the Playbook source banner on Organization Skill pages, and Platform Settings → Playbooks; `source_agent_name` on run reads.
- Delivered: install shortcuts on a published playbook's Skill page — Add to Agents and Require on a Template — built on the existing Agent update and Template draft contracts.
- Delivered: the role/conventions split — runs propose Organization Conventions kept apart from the role playbook, and people add reviewed rules to Template drafts' AGENTS.md.
- In transition: nothing.
- Next: none; every v1 slice is delivered. Closing the epic waits on review, merge, and tickets for the deferred items below.
- Deferred: compiling playbooks into configuration, scheduled re-extraction, Connection exclusions, reading the Agent volume, automatic publication, and measuring playbook impact.
- Blockers: none.

## Changes

### 2026-10-14 — clearer outputs in the UI

- Changed: a finished run shows its two outputs as labelled cards, the Role playbook (for Agents in the same role) and Organization conventions (for every Agent), each with its own review action; the status reads Ready to review; the create form explains both outputs; the Skill page banner says it is the role playbook and links to the same run's conventions.
- Why: after a run, people opened the sales Skill draft and missed the role-independent conventions on the same run.

### 2026-10-14 — fix: cut-off playbook answers

- Found: in a live run with `openrouter/anthropic/claude-haiku-5.5` the playbook step stopped at its 4,000-token limit, so its JSON was cut off and the run failed with `model_error` after spending about $0.018.
- Changed: the playbook step allows 12,000 output tokens; a completion that stops at its limit (`finish_reason: length`) fails the run with the new `answer_truncated` code; JSON wrapped in a Markdown code fence is accepted; the preview estimates 3,000 output tokens for the playbook.

### 2026-10-14 — slice 7: Organization Conventions

- Decided: a role playbook suits Agents in the same role, while firm-wide rules belong to every Agent; they go to Template AGENTS.md, which every Agent loads at startup, rather than a Skill an Agent opens only when its description matches.
- Delivered: prompt `playbook-2026-10-14` with `conventions`, migration `cd4c6b9354f9` (`result_conventions`), `convention_count` and `conventions` on run reads, `POST .../templates/{template_key}/draft/conventions`, and the Review conventions dialog.
- Verified: merge unit tests, endpoint and pipeline integration tests, and Playwright for reviewing, editing, and adding conventions.
- Follow-up: none.

### 2026-10-13 — slice 6

- Delivered: `PlaybookInstallActions` in the Playbook source banner; no API change.
- Verified: Playwright for adding to and repinning Agents with a per-Agent refusal, adding to a Template draft while keeping other requirements, an already-required Template, and an unpublished playbook.
- Follow-up: none in this epic; see Deferred.

### 2026-10-13 — slice 5

- Delivered: `ui/src/features/playbooks/` and the Agent page tab, the Skill page banner, and the Platform Settings section; Platform Settings now switches sections with `?section=`.
- Changed: the Agent Memory model card moved into the shared `ModelSettingCard`, unchanged for users; run reads carry `source_agent_name`.
- Verified: Playwright for the tab, run states, Member hiding, the Platform setting, and the banner; the existing Platform memory, Agent detail, Agent memory, RBAC, and Skill specs still pass.
- Follow-up: slice 6, install shortcuts.

### 2026-10-13 — slice 4

- Delivered: `PlaybookPipeline`, its prompts (`playbook-2026-10-13`, revised to `.2` after a live check), `SkillService.write_playbook_draft`, and output-token and model fields on the preview.
- Removed: the transitional `pipeline_unavailable` error code.
- Changed: the Compose worker receives `MEMORY_VIEW_BASE_URL`; Helm already supplies it through the API Secret.
- Verified live: one run over 20 local sales conversations with `openrouter/openai/gpt-4.1-mini` made 21 calls, about 56k prompt and 9k completion tokens, roughly $0.03, and produced a usable playbook with real commands, standards, and corrections. It reported no open questions despite single-conversation procedures, so the instruction was tightened.
- Follow-up: slice 5, the UI.

### 2026-10-13 — slice 3

- Delivered: `GET/PUT /api/v1/platform/settings/playbooks` and `/models`, migration `a77ac74c3fad`, the `platform.playbook_model.changed` event, and `LiteLLMCompletionClient`.
- Changed: the worker Deployment and Compose service receive `LITELLM_BASE_URL`; `PLAYBOOK_DEFAULT_MODEL` is optional.
- Follow-up: slice 4, the pipeline.

### 2026-10-13 — slice 2

- Delivered: `GET .../playbook-extractions/preview` and the session reader the pipeline will use.
- Found: Conversation Message `session_key` and Tool Call `session_id` never match (0 of 50 runtime sessions in local data), so Tool Calls are paired to conversations by time span. On local data the pairing matched each Slack thread with the runtime session that served it.
- Changed: `AgentAuthorization.membership_scope`, so the worker can read with the requesting Membership's own scope.
- Follow-up: slice 3, the model setting and completion client.

### 2026-10-13 — slice 1

- Delivered: the `playbooks` domain, migration `5ae205b73312`, the product APIs under `/organizations/{organization_id}/agents/{agent_id}/playbook-extractions` and `/organizations/{organization_id}/playbook-extractions`, the audit event, and the worker actor.
- Changed: the RBAC brief, Domain Events, system map, runtime and deployment, Templates and Skills, and INDEX docs.
- Follow-up: slice 2, session assembly and the preview endpoint.

### 2026-10-13 — slice 0

- Delivered: this log, the glossary terms, and the INDEX route.
- Follow-up: slice 1.
