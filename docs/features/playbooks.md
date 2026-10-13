# Playbooks

## Read when

Read before changing Playbook Extractions: who may start or read them, what they read from a source Agent, how the worker runs them, or how their output reaches an Organization Skill.

## Role in the system

A Playbook is an Organization Skill whose content came from a source Agent's work and was reviewed by a person before publishing. A **Playbook Extraction** is one recorded run that reads the source Agent's sessions and writes the result into an Organization Skill Draft. Publishing, assigning the Skill to Agents, and requiring it on Templates use the ordinary [Skill](templates-and-skills.md) workflows; a run never publishes or installs anything.

Delivery is staged; see [`playbooks/CHANGELOG.md`](playbooks/CHANGELOG.md). Runs are accepted, audited, queued, and authorized in the worker. The pipeline that reads sessions and writes the draft is not delivered yet: every run that reaches it fails with `pipeline_unavailable`.

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
- Stored error codes: `enqueue_failed`, `requester_lost_access`, `source_agent_unavailable`, `pipeline_unavailable`, `no_sessions`, `model_unavailable`, `spend_limit_reached`, `model_error`, `draft_conflict`, `skill_unavailable`, `internal_error`. Upstream error text and content are never stored or logged.

## Primary flows

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

## Data contract

`playbook_extraction` belongs to its Organization and source Agent through a composite foreign key, and is deleted with either. `requested_by_membership_id`, `requested_by_user_id`, and `skill_id` are set to `NULL` when what they reference is deleted. When the target Skill is deleted before the run writes, the run creates a new lineage named `skill_name` instead.

Each run records the window, session bound, model, prompt version, the selected session keys, input counts, token usage, and cost, so a later compilation step can rebuild from the same inputs.

## Change impact

| Change | Also update |
| --- | --- |
| Who may start or read runs | This document, [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md), the worker authority check in `api/domains/playbooks/processor.py` |
| Run schema or status values | Alembic migration, `api/domains/playbooks/models.py`, the UI schema |
| Audit payload | `api/domains/events/catalog.py`, [`domain-events.md`](domain-events.md) |
| Worker queue, time limit, or retries | `api/domains/playbooks/constants.py`, `api/worker_app.py`, [`../architecture/runtime-and-deployment.md`](../architecture/runtime-and-deployment.md) |
| What counts as a valid target Skill | `SkillService.require_playbook_target`, [`templates-and-skills.md`](templates-and-skills.md) |

## Code map

- `api/domains/playbooks/`: models, repository (scoped reads, conditional transitions), service (authorization and orchestration), routes, the queue (`transport.py`), the worker processor and entry point, and the pipeline.
- `api/worker_app.py`: the `playbook_extraction.process` Dramatiq actor on the `playbook_extraction` queue.
- `api/domains/skills/service.py`: `require_playbook_target` and `require_available_organization_skill_name`.
- `api/tests/integration/test_playbook_extractions.py`, `api/tests/steps/playbooks.py`: authorization, tenancy, conflicts, audit, cancellation, and the worker's claim and authority checks.
