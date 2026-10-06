# Agents and activity

All Agent endpoints use `/api/v1/organizations/{organization_id}/agents`. `GET` lists visible Agents with pagination (`page`, `page_size`); `POST` creates an Agent. `GET`, `PATCH`, and `DELETE` on `/{agent_id}` retrieve, update, and remove it. `POST /{agent_id}/start` and `/stop` manage its runtime. `GET /{agent_id}/healthz` reports health. Request and response shapes are in [OpenAPI](/api/v1/openapi.json).

Configuration lives at `/{agent_id}/configuration`. Draft creation, editing, publishing, and version selection use the `/configuration/draft`, `/configuration/draft/publish`, and `/configuration/select` endpoints. Agent sharing uses `/share` and the organization-level `/agents/share-roles` catalogue. These actions require their matching Agent Permissions; the Agent response advertises the current caller's allowed actions.

Activity includes `/{agent_id}/conversations/channels`, channel messages, tool calls, logs, log history, and the server-sent event log stream at `/{agent_id}/logs/stream`. Costs are under `/organizations/{organization_id}/costs` and `/costs/agents/{agent_id}`. Collection results use the documented pagination or cursor parameters. The streaming endpoint emits `text/event-stream`; use a streaming HTTP client and reconnect if the connection drops.

Runtime telemetry sent by deployed Agents enters the separate `/ingest/v1` application with runtime credentials. Personal API keys are for the product API.
