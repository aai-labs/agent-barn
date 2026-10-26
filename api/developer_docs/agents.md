# Agents and activity

All Agent endpoints use `/api/v1/organizations/{organization_id}/agents`. `GET` lists visible Agents with pagination (`page`, `page_size`); `POST` creates an Agent. `GET`, `PATCH`, and `DELETE` on `/{agent_id}` retrieve, update, and remove it. `POST /{agent_id}/start` and `/stop` manage its runtime. `GET /{agent_id}/healthz` reports health. Request and response shapes are in [OpenAPI](/api/v1/openapi.json).

Configuration lives at `/{agent_id}/configuration`. Draft creation, editing, publishing, and version selection use the `/configuration/draft`, `/configuration/draft/publish`, and `/configuration/select` endpoints. Agent sharing uses `/share` and the organization-level `/agents/share-roles` catalogue. These actions require their matching Agent Permissions; the Agent response advertises the current caller's allowed actions.

Activity includes `/{agent_id}/conversations/channels`, channel messages, tool calls, logs, log history, and the server-sent event log stream at `/{agent_id}/logs/stream`. Costs are under `/organizations/{organization_id}/costs` and `/costs/agents/{agent_id}`. Collection results use the documented pagination or cursor parameters. The streaming endpoint emits `text/event-stream`; use a streaming HTTP client and reconnect if the connection drops.

Runtime telemetry sent by deployed Agents enters the separate `/ingest/v1` application with runtime credentials. Personal API keys are for the product API.

## Create and save workflows (WF01)

Check `GET /{agent_id}/workflow-capabilities` before authoring. Build the full
workflow snapshot manually; natural-language draft generation is deferred to a
separate PR and has no endpoint in this slice.

Explicitly save the reviewed full snapshot with `POST /{agent_id}/workflows`.
List compact card summaries with `GET /{agent_id}/workflows`: each version
contains its name, description and step/input counts, without the full draft.
Read the complete saved snapshot with `GET /{agent_id}/workflows/{id}`;
inspect immutable history with `GET /{agent_id}/workflows/{id}/versions`.
Collections use `page` and `page_size`. To save another version, submit the full
`draft` and `expected_revision` to `POST /workflows/{id}/versions`; handle stale
409 responses by inspecting the latest definition and reviewing your draft.
`POST /workflows/{id}/archive` also requires `expected_revision` and retains
saved versions. Reads require current Agent read permission; authoring requires
Agent update permission and a full-access key. Consult [OpenAPI](/api/v1/openapi.json)
for the complete bounded schema and response fields.

Saving never starts execution. Web remains the only saved review destination.

## Run workflows and inspect text results (WF02)

When the separate execution capability is enabled,
`POST /{agent_id}/workflows/{id}/runs` accepts an explicit `version_id`, a UUID
`client_request_id` and typed `inputs`, returning 202 with the queued run.
Retry an uncertain start with the same identity and body; conflicting reuse returns
409. The Agent must be running; otherwise a new start returns 409.
Each step runs as a new session inside the owning Agent, using its current tools,
Integrations, model, approval mode and spend limits. The run pins its saved workflow
version and inputs, not an image or model. Declared step capabilities do not gate
admission. Sessions share the Agent's environment and workspace. If a step needs
human attention, such as a command approval, the run becomes `BLOCKED`; WF02 has
no approval or resume operations.

Inspect paginated `/{agent_id}/workflow-runs` (optionally `workflow_id`), individual
`/workflow-runs/{run_id}` and `/history`. Run detail includes each completed
step's text `summary` and, after success, `final_summary`. Later steps receive
completed text summaries as context. Cancel with
`POST /workflow-runs/{run_id}/cancel` and `expected_revision`. Start and cancel
require current Agent update permission and a full-access key; run/history reads
currently use Agent read permission. Server `allowed_actions` advertises whether
the caller can cancel.

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
