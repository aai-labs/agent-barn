# Playbooks

## Read when

Read before changing Playbook Extractions: who may start or read them, what they read from a source Agent, how the worker runs them, or how their output reaches an Organization Skill.

## Role in the system

A Playbook is an Organization Skill whose content came from a source Agent's work and was reviewed by a person before publishing. It describes how that Agent's role works, so it suits Agents in the same role. A run also proposes **Organization Conventions**: rules any Agent in the Organization should follow whatever its role, which people review and add to Templates' AGENTS.md instead of the Skill. A **Playbook Extraction** is one recorded run that reads the source Agent's sessions and writes the result into an Organization Skill Draft. Publishing, assigning the Skill to Agents, and requiring it on Templates use the ordinary [Skill](templates-and-skills.md) workflows; a run never publishes or installs anything.

Delivery is staged; see [`playbooks/CHANGELOG.md`](playbooks/CHANGELOG.md).

## Authorization

- Every Playbook Extraction surface needs the Agent Permission `activity.read` on the source Agent, because a run reads its transcripts, and the Organization Permission `skill.manage`, because a run writes an Organization Skill. In practice only Organization Owners and Admins qualify. An Agent the caller cannot see is `404`; a visible Agent without both Permissions is `403`.
- The Organization-wide run list needs `skill.manage` and returns only runs whose source Agent the caller can read and that is not deleted.
- Publishing a Playbook makes content derived from one Agent's transcripts visible to every Organization Member through `skill.read`, including Members who cannot see that Agent. The person publishing is an Owner or Admin who reviewed the draft; that review is the control. The draft itself is readable only with `skill.manage`.
- A person starts the run, so the worker does not use the RBAC brief's background-work exception. When a run starts, the worker re-checks that the requesting Membership still exists, still holds `skill.manage` through its Organization Role, and still holds `activity.read` on the undeleted source Agent. Otherwise the run fails with `requester_lost_access` or `source_agent_unavailable` before reading anything.

## State model

| Status | Meaning |
| --- | --- |
| `QUEUED` | Accepted and handed to the worker queue |
| `RUNNING` | Claimed by a worker |
| `SUCCEEDED` | The playbook was written |
| `FAILED` | Stopped; `error_code` says why |
| `CANCELLED` | Cancelled by a person before finishing |

- A source Agent has at most one `QUEUED` or `RUNNING` run (`uq_playbook_extraction_active_agent`); a second start is `409`.
- The worker claims a run only while it is `QUEUED`, or `RUNNING` with a start more than 30 minutes old, which means a worker died mid-run. A redelivered message therefore never processes a live run twice. Every later transition is conditional on the run still being active, so a cancelled run keeps `CANCELLED` even if a worker finishes after the cancellation.
- Runs are never retried automatically, because model calls are billed. A failed run is started again by a person.
- Stored error codes: `enqueue_failed`, `requester_lost_access`, `source_agent_unavailable`, `no_sessions`, `model_unavailable`, `spend_limit_reached`, `model_error`, `answer_truncated`, `draft_conflict`, `skill_unavailable`, `internal_error`. Upstream error text and content are never stored or logged.

## What a run reads

- The source Agent's conversations, by Conversation Message `session_key`, whose messages fall inside the window: the most recently active first, up to the run's session bound. Each conversation contributes at most its latest 200 messages in the window. Web Chat conversations are included.
- The Tool Calls its runtime made in those conversations. Runtimes report Tool Calls under their own runtime session ID, which never matches the conversation's `session_key`, so each runtime session is paired with the conversation whose time span, widened by 30 seconds on each side, contains it; among several, the shortest span wins. Runtime sessions that no selected conversation contains, such as startup and internal maintenance work, are not read. A paired runtime session contributes at most its first 300 Tool Calls.
- Each conversation becomes one plain-text transcript, with messages and Tool Calls in time order. Messages are clipped at 4,000 characters, Tool Call arguments at 1,000, and results at 1,500. A transcript over 40,000 characters is rendered again with arguments and results clipped at 300, and cut at 40,000 if still too long.
- All reads join the source Agent through the caller's visibility scope; in the worker that is the requesting Membership's scope.

## Primary flows

### Preview a run

`GET .../agents/{agent_id}/playbook-extractions/preview?window_days=&max_sessions=` uses the same authorization and bounds as starting a run and returns what a run would read now: the window, `session_count`, `message_count`, `tool_call_count`, `input_chars`, the current `model`, and `estimated_input_tokens` and `estimated_output_tokens`. Estimates count four characters per token for the transcripts and both prompts, plus a typical 400 tokens of notes per conversation and 3,000 for the playbook; they exclude long-term memories. Previewing reads nothing from Hindsight, calls no model, and records nothing.

### Start a run

`POST /organizations/{organization_id}/agents/{agent_id}/playbook-extractions` returns `202` with the queued run.

- The body names exactly one target: `skill_name` for a new playbook, or `skill_id` for the next draft of an existing one. Both or neither is `422`.
- A new playbook's name must not already belong to an Organization Skill (`409`).
- An existing target must be an Organization-owned custom Skill (`403` for a Platform, built-in, or Agent Skill) with no pending draft (`409`), so a run never overwrites a person's unpublished edits.
- `window_days` (1–365, default 30) sets a window ending now; `max_sessions` (1–50, default 20) bounds how many sessions the run reads.
- The run and the Organization-scoped `playbook.extraction.requested` Domain Event commit together. The event's Subject is the source Agent; its payload carries IDs, the target name, the window length, the session bound, and display snapshots, never content. It is projected by `security_audit.projection`.
- If the worker queue is unavailable, the run is marked `FAILED` with `enqueue_failed` and the request returns `503`.

### Read and cancel runs

- `GET .../agents/{agent_id}/playbook-extractions` lists an Agent's runs newest first, paginated.
- `GET /organizations/{organization_id}/playbook-extractions?skill_id=` lists the Organization's runs, optionally for one target Skill.
- `GET .../playbook-extractions/{extraction_id}` adds `result_markdown`, the generated playbook, kept on the run so nothing paid for is lost if the draft cannot be written.
- `POST .../playbook-extractions/{extraction_id}/cancel` cancels a `QUEUED` or `RUNNING` run; a finished run is `409`.

## Pipeline

The worker runs these steps once the requester's authority is confirmed. After each step it stores its figures only while the run is still `RUNNING`; a cancellation stops it at the next step.

1. Read the transcripts (see [What a run reads](#what-a-run-reads)) and record the session keys and counts. No transcript fails the run with `no_sessions` before any model call.
2. Take notes on each transcript, four at a time, asking the model for a JSON object with the task, whether it teaches anything reusable, the steps, tools, people's corrections, their preferences, and the outcome. A non-JSON answer is kept as text. Notes marked not reusable are dropped unless nothing else is left.
3. Read up to 200 of the source Agent's long-term memories, each clipped to 500 characters, through the memory viewer with a capability for that Agent. They include Organization Memory only while the Agent holds a read grant, as in the Agent Memory tab. If memory is unavailable the run continues without it.
4. Ask the model for the playbook from the notes and memories: a one-sentence description of when to use it; a list of proposed Organization Conventions, each one imperative sentence that names none of this role's tools, commands, data sources, or tasks, with how many conversations support it; and a Markdown body that does not repeat them, with fixed sections (when to use, how we work, tools and commands, preferences and standards, corrections to avoid, open questions for the reviewer), each procedure citing how many conversations support it. The step allows up to 12,000 output tokens; an answer the model stops at that limit fails the run with `answer_truncated`, and one in another shape with `model_error`. A JSON answer wrapped in a Markdown code fence is accepted, here and for notes; malformed conventions are dropped without failing it, and at most 30 are kept, each clipped to 500 characters.
5. Store the playbook on the run as `SKILL.md`, and the proposed conventions as `result_conventions`, with `name` (the mount slug) and `description` frontmatter, then write it as a Skill Draft: the next draft of the target Skill, or a new custom Organization Skill named `skill_name`, with ` (2)`, ` (3)`, … added if that name was taken meanwhile. A target that gained a draft after the request fails the run with `draft_conflict`, leaving that draft untouched; the generated playbook stays on the run.

Both prompts tell the model to describe practices generically and leave out names of people, clients, and companies, contact details, identifiers, client amounts, and credentials, and to treat transcripts, notes, and memories as data rather than instructions. These are instructions to a model, not a guarantee: the reviewer publishing the draft remains the control. Each run records `prompt_version`.

Model failures map to stored codes: budget exceeded to `spend_limit_reached`, a rejected key or model to `model_unavailable`, and an outage or empty answer to `model_error`. A missing or undecryptable Agent key is `model_unavailable`. Tokens and cost spent before a failure stay on the run.

## Model and billing

- Platform Administrators choose the extraction model at `GET/PUT /api/v1/platform/settings/playbooks`; `GET .../models` lists the OpenRouter catalogue's text models as `openrouter/<id>`. Organization roles confer no authority on these routes, and Organization model allowlists do not apply. Without a saved choice, `PLAYBOOK_DEFAULT_MODEL` (default `openrouter/openai/gpt-4.1-mini`) applies. A saved model must be in the catalogue; an unavailable catalogue is `503` and changes nothing. A change and its Platform-scoped `platform.playbook_model.changed` audit event commit together in `platform_playbook_settings`; saving the current choice records nothing. A run uses the model in force when it starts.
- A run calls `POST /chat/completions` on the LiteLLM proxy with the source Agent's own LiteLLM key, decrypted in the worker. The spend is therefore attributed to that Agent by cost sync, appears on its Costs tab, and counts against the Agent's and its Organization's LiteLLM budgets, which LiteLLM enforces. Agent keys allow every model, so no key allowlist changes.
- The completion client sends no environment proxy or redirect, never stores or logs request or response content, and classifies failures as budget exceeded (a `400` or `429` whose error names a budget), key or model rejected (other `400`, `401`, `403`, `404`), unavailable (other statuses and transport errors), or a bad response (no text). Token usage comes from the response; cost comes from LiteLLM's `x-litellm-response-cost` header and is unknown rather than zero when absent.

## User interface

- Agent page → **Playbooks** (`?tab=playbooks`) appears only for people with `activity.read` on the Agent whose Organization Role is Owner or Admin; a Platform Administrator who is only a Member does not see it, and no playbook requests are sent for anyone else. It holds a create form and the Agent's runs.
- The form writes to **a new playbook** (named `<Agent> playbook` by default) or **the next draft of a playbook**, offering the Skills earlier runs in the Organization wrote to. Period (7, 30, or 90 days) and conversation bound (10, 20, or 50) refresh the preview, which shows what the run would read, the estimated tokens, and the model. Create is disabled while a run is active or when the period has no conversations.
- Runs list newest first, refreshing every three seconds while one is queued or running, with what each read, its tokens, cost, and model. A finished run links to **Review draft** on its Organization Skill page; a failed run explains its error code; a `draft_conflict` run offers **View playbook** to read the kept result; an active run can be cancelled after confirmation.
- A finished run that proposed conventions offers **Review conventions (N)**. The dialog lists each proposed rule with how many conversations support it; people untick or edit rules and choose Organization Templates, and the chosen rules are added to each Template's draft through [the Template conventions contract](templates-and-skills.md#add-organization-conventions-to-a-template). Each Template reports its own result with a link to open it. Nothing is published: Agents created from each newly published Template version receive the conventions, and existing Agents receive them when switched to that version.
- An Organization Skill page that a successful run wrote shows a **Playbook source** banner to people who can manage Skills: the source Agent, when and from how many conversations and memories it was extracted, and, while a draft exists, what to check before publishing — including that publishing makes it visible to every member.
- Once the playbook has a published version, the banner offers two install shortcuts that use the existing Agent and Template contracts; nothing is installed without one of them:
  - **Add to Agents** lists the Organization's Agents the person may update (`agent.update`), with the version each already pins. Selected Agents without the Skill are sent `skill_ids` plus a `skill_versions` pin to the published version; Agents on an older version are sent only the pin. Each Agent is updated separately, so a refusal such as a missing provider credential is shown for that Agent alone. Running Agents load it on their next restart.
  - **Require on a Template** gets or starts the chosen Organization Template's draft and, unless the draft already requires the Skill, adds it as a standalone requirement pinned to the published version while the server keeps the other requirements, groups, and pins. The person reviews and publishes the Template draft; Agents created from the next published version receive the playbook, and existing Agents keep their Skills.
- Platform Settings → **Playbooks** (`/dashboard/platform/settings?section=playbooks`) holds the model setting; the model picker card is shared with Agent Memory.
- Agent-level queries live under the Agent's query family; Organization-level run lists use the `playbook-extractions` family, which is evicted on an Organization switch and keyed by the Organization API base.

## Data contract

`playbook_extraction` belongs to its Organization and source Agent through a composite foreign key, and is deleted with either. `requested_by_membership_id`, `requested_by_user_id`, and `skill_id` are set to `NULL` when what they reference is deleted. When the target Skill is deleted before the run writes, the run creates a new lineage named `skill_name` instead.

Each run records the window, session bound, model, prompt version, the selected session keys, input counts, token usage, cost, and the proposed conventions (`result_conventions`, exposed on reads as `convention_count` and, in detail, `conventions`), so a later compilation step can rebuild from the same inputs.

## Change impact

| Change | Also update |
| --- | --- |
| Who sees the Playbooks tab or provenance banner | `ui/src/features/agents/components/agent-detail-page.tsx`, `ui/src/features/playbooks/`, the e2e specs |
| Who may start or read runs | This document, [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md), the worker authority check in `api/domains/playbooks/processor.py` |
| Run schema or status values | Alembic migration, `api/domains/playbooks/models.py`, the UI schema |
| Audit payload | `api/domains/events/catalog.py`, [`domain-events.md`](domain-events.md) |
| Model setting or completion request shape | `api/domains/playbooks/platform_service.py`, `api/infrastructure/litellm/completions.py`, the Platform settings UI |
| Worker queue, time limit, or retries | `api/domains/playbooks/constants.py`, `api/worker_app.py`, [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md) |
| Organization Conventions section or merge rules | `api/domains/templates/conventions.py`, [`templates-and-skills.md`](templates-and-skills.md#add-organization-conventions-to-a-template) |
| Prompts or output shape | `api/domains/playbooks/prompts.py` and its `PROMPT_VERSION`, this document |
| Session selection, pairing, or transcript bounds | This document, `api/domains/playbooks/transcripts.py`, `api/domains/playbooks/repository.py` |
| What counts as a valid target Skill | `SkillService.require_playbook_target`, [`templates-and-skills.md`](templates-and-skills.md) |

## Code map

- `api/domains/playbooks/`: models, repository (scoped reads, conditional transitions, bounded session reads), service (authorization and orchestration), routes, the queue (`transport.py`), the worker processor and entry point, the session reader (`sessions.py`), transcript pairing and rendering (`transcripts.py`), and the pipeline.
- `api/domains/playbooks/pipeline.py`, `prompts.py`: the model steps and their instructions.
- `api/domains/playbooks/platform_*.py`: the Platform model setting.
- `api/infrastructure/litellm/completions.py`: chat completions billed to a supplied virtual key.
- `api/worker_app.py`: the `playbook_extraction.process` Dramatiq actor on the `playbook_extraction` queue.
- `ui/src/features/playbooks/`: the Agent tab, run list, provenance banner, and Platform setting; `ui/src/features/platform-settings/` composes the Platform Settings sections; `ui/src/components/settings/model-setting-card.tsx` is the shared model picker.
- `api/domains/skills/service.py`: `require_playbook_target`, `require_available_organization_skill_name`, and `write_playbook_draft`.
- `api/tests/integration/test_playbook_extractions.py`, `api/tests/steps/playbooks.py`: authorization, tenancy, conflicts, audit, cancellation, and the worker's claim and authority checks.
- `api/tests/integration/test_playbook_pipeline.py`, `api/tests/helpers/litellm_proxy.py`: whole runs against a loopback LiteLLM proxy.
- `api/tests/integration/test_platform_playbook_settings.py`, `api/tests/unit/test_litellm_completions.py`: the Platform setting and the completion client against a loopback proxy.
- `ui/tests/e2e/agent-playbooks.spec.ts`, `ui/tests/e2e/settings-skill-detail-page.spec.ts`, `ui/tests/e2e/playbook-install.spec.ts`: the tab, run list, Platform setting, provenance banner, and install shortcuts.
- `api/tests/integration/test_playbook_extraction_preview.py`, `api/tests/unit/test_playbook_transcripts.py`: session selection, pairing, rendering bounds, and the estimate.
