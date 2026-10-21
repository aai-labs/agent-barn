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

Saving never starts execution. When the separate execution capability is enabled,
`POST /{agent_id}/workflows/{id}/runs` accepts an explicit `version_id`, a UUID
`client_request_id` and typed `inputs`, returning 202 with the queued run.
Retry an uncertain start with the same identity and body; conflicting reuse returns
409. Only reasoning capabilities are admitted; protected actions and native
commands return 422. The Agent must be running; tagged runtime images are
automatically pinned to the running Agent container's pullable Kubernetes image
identity. If that identity is not available yet, start returns 409; cluster lookup
failures return 503, with no queued run.
Web remains the only saved review destination; WF02 has no approval operations.

Inspect paginated `/{agent_id}/workflow-runs` (optionally `workflow_id`), individual
`/workflow-runs/{run_id}` and `/history`. Run detail includes each completed
step's text `summary` and, after success, `final_summary`. Later steps receive
completed text summaries as context. Cancel with
`POST /workflow-runs/{run_id}/cancel` and `expected_revision`; cancellation fences
new admission while existing claimed work stops. Completed summaries remain
available. File artifacts, storage, preview and download endpoints are deferred.

Platform Administrators manage installation-wide authoring through
`GET/PUT /api/v1/platform/settings/workflows`. The update body is
`{"authoring_enabled": true}` (or `false`); responses include the effective
`authoring_enabled` and nullable `updated_at`. A saved choice overrides the
initial off default without granting Agent permissions. Disabling authoring
retains API inspection and history. Execution has its own deployment admission flag.
