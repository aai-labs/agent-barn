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
- In transition: nothing.
- Next, in order:
  1. Domain skeleton: the `playbooks` domain, the `playbook_extraction` table, create/list/detail/cancel endpoints, authorization, the audit Domain Event, and a worker actor that re-checks the requester's authority.
  2. Session assembly: bounded transcript reads for one Agent and a preview endpoint with an estimated input token count.
  3. Model setting and completion client: the Platform Playbook model setting and a LiteLLM chat-completion client using the source Agent's key.
  4. Pipeline: per-session notes, one combining call with long-term memories, writing the Skill Draft, and recording usage.
  5. UI: Create playbook on the Agent page, run history, the Platform setting, and a provenance banner on the Skill Draft.
  6. Install shortcuts: from a published playbook, assign it to Agents or require it on a Template.
- Deferred: compiling playbooks into configuration, scheduled re-extraction, Connection exclusions, reading the Agent volume, automatic publication, and measuring playbook impact.
- Blockers: none.

## Changes

### 2026-10-13 — slice 0

- Delivered: this log, the glossary terms, and the INDEX route.
- Follow-up: slice 1.
