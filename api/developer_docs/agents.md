# Agents and activity

All Agent endpoints use `/api/v1/organizations/{organization_id}/agents`. `GET` lists visible Agents with pagination (`page`, `page_size`); `POST` creates an Agent. `GET`, `PATCH`, and `DELETE` on `/{agent_id}` retrieve, update, and remove it. `POST /{agent_id}/start` and `/stop` manage its runtime. `GET /{agent_id}/healthz` reports health. Request and response shapes are in [OpenAPI](/api/v1/openapi.json).

Configuration lives at `/{agent_id}/configuration`. Draft creation, editing, publishing, and version selection use the `/configuration/draft`, `/configuration/draft/publish`, and `/configuration/select` endpoints. Agent sharing uses `/share` and the organization-level `/agents/share-roles` catalogue. These actions require their matching Agent Permissions; the Agent response advertises the current caller's allowed actions.

Activity includes `/{agent_id}/conversations/channels`, channel messages, tool calls, logs, log history, and the server-sent event log stream at `/{agent_id}/logs/stream`. Costs are under `/organizations/{organization_id}/costs` and `/costs/agents/{agent_id}`. Collection results use the documented pagination or cursor parameters. The streaming endpoint emits `text/event-stream`; use a streaming HTTP client and reconnect if the connection drops.

Runtime telemetry sent by deployed Agents enters the separate `/ingest/v1` application with runtime credentials. Personal API keys are for the product API.

## Create and save workflows (WF01)

Workflows belong to the Organization, not to an Agent. Their endpoints use
`/api/v1/organizations/{organization_id}`, with no Agent in the path.

Check `GET /workflow-capabilities` before authoring. Build the full
workflow snapshot manually; natural-language draft generation is deferred to a
separate PR and has no endpoint in this slice.

Explicitly save the reviewed full snapshot with `POST /workflows` and the body
`{"draft": {...}, "default_agent_id"?: "<agent id>"}`. The optional default Agent
is only preselected when a run is started; it grants no access.
List compact card summaries with `GET /workflows` (optionally
`created_by_me=true` or `archived=true|false`): each version
contains its name, description and step/input counts, without the full draft.
Read the complete saved snapshot with `GET /workflows/{id}`;
inspect immutable history with `GET /workflows/{id}/versions`.
Collections use `page` and `page_size`. To save another version, submit the full
`draft` and `expected_revision` to `POST /workflows/{id}/versions`; handle stale
409 responses by inspecting the latest definition and reviewing your draft.
`PATCH /workflows/{id}` with `expected_revision` and `default_agent_id` (or `null`)
changes the default Agent without saving a version.
`POST /workflows/{id}/archive` also requires `expected_revision` and retains
saved versions. Every Member of the Organization can read and create workflows;
saving a version, changing the default Agent and archiving are limited to the
workflow's creator and Organization Owners and Admins (403 otherwise), and need a
full-access key. Describe what a step should produce in its `goal`; the separate
`artifact_description` field is legacy and is folded into the goal on save.
Consult [OpenAPI](/api/v1/openapi.json)
for the complete bounded schema and response fields.

Saving never starts execution. Web remains the only saved review destination.

## Run workflows and inspect text results (WF02)

When the separate execution capability is enabled,
`POST /workflow-runs` accepts the `workflow_id`, the `agent_id` of the Agent that
should run it, an explicit `version_id`, a UUID `client_request_id`, typed
`inputs` and an optional `title`, returning 202 with the queued run.
Retry an uncertain start with the same identity and body; conflicting reuse,
including the same identity with a different Agent, returns
409. The Agent must be running; otherwise a new start returns 409.
Each step runs as a new session inside that Agent, using its current tools,
Integrations, model, approval mode and spend limits. The run pins its Agent, saved workflow
version and inputs, not an image or model. Declared step capabilities do not gate
admission. Sessions share the Agent's environment and workspace. When a Hermes step
asks to run a flagged command, the run shows the request in `approval`; anyone with
`agent.update` on the run's Agent decides with `POST /workflow-runs/{run_id}/approvals/{request_id}/decision`
(`{"decision": "approve" | "decline", "guidance"?}`). Unanswered requests move the
run to `AWAITING_APPROVAL`; a late decision continues the step's session. List
runs awaiting a decision with `GET /workflow-runs?awaiting_decision=true`.

Inspect paginated `/workflow-runs` (optionally `workflow_id`, `agent_id` and
`status=active|settled`), individual
`/workflow-runs/{run_id}` and `/history`. The list returns only runs on Agents you
can read. Each run names its Agent in `agent_id` and `agent_name`;
`agent_archived` is true once that Agent was deleted, after which the run can only
be read. Run detail includes each completed
step's text `summary` and, after success, `final_summary`. Later steps receive
completed text summaries as context. Cancel with
`POST /workflow-runs/{run_id}/cancel` and `expected_revision`. Start, re-run, cancel
and decide require current Agent update permission on the run's Agent and a
full-access key; run/history reads use Agent read permission on it, and a run you
cannot read returns 404. Server `allowed_actions` advertises whether
the caller can cancel, re-run or decide.

Repeat a settled run with `POST /workflow-runs/{run_id}/re-run` and a UUID
`client_request_id` only: the server copies the original run's Agent, pinned version,
title and inputs (the body accepts nothing else) and returns 202 with a new run whose
`rerun_of_run_id` is the original and whose history starts with a `RERUN_STARTED`
entry. It needs the same permission, running Agent and non-archived workflow as a
start. A run that has not settled, or whose inputs were removed by retention,
returns 409; retries with the same identity return the same run. The original run
is unchanged. `allowed_actions` includes `rerun` when it is available.

Cancellation fences new workflow handoffs/results and requests session stop where
supported. Stop is best effort; cancellation does not prove that all tools have
stopped or undo external effects. Completed summaries remain available. Failed or
expired unfinished steps can currently be retried automatically; duplicate-safe
dispatch does not guarantee exactly-once external effects. The planned handling
of uncertain effects is not yet implemented. A text summary is the Agent's report,
not independent verification of a provider receipt or published file bytes.
File artifacts, storage, preview and download endpoints are deferred to a separate
slice.

## Platform workflow authoring setting

Platform Administrators manage installation-wide authoring through
`GET/PUT /api/v1/platform/settings/workflows`. The update body is
`{"authoring_enabled": true}` (or `false`); responses include the effective
`authoring_enabled` and nullable `updated_at`. A saved choice overrides the
initial off default without granting Agent permissions. Disabling authoring
retains API inspection and history. Execution has its own deployment admission flag.

For integration changes, `PATCH /{agent_id}` accepts `restart: true` to validate proposed credentials while the Agent runs, then stop, save and start under one lifecycle lock. Omit `restart` to retain stopped-only update behavior. Credential changes require `agent.secret.manage` alongside `agent.update`; restarting additionally requires `agent.lifecycle.manage`. Optional isolation `policies` and a `custom_api` batch are validated in the same request before runtime teardown. Invalid credentials leave a running Agent and its previous settings untouched. A persistence or startup failure after validation can leave saved changes and a stopped or failed Agent; inspect its current state before retrying. The restart option is limited to integration changes.

Live credential validation failures on integration apply requests return `detail: {"code": "INTEGRATION_VALIDATION_FAILED", "provider": "apollo", "message": "Apollo credential: Invalid API key"}` (400 for a rejected credential, 503 if validation is unavailable). This code identifies a failure before writes or runtime teardown, so no requested changes were saved. The first failed validation ends the request. Ordinary stopped-only PATCH requests retain their existing error format.
