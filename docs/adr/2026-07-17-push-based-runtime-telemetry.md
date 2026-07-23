# Use push-based runtime telemetry

Status: Accepted (retrospective)
Date: 2026-07-17
Origin: AF-122

Conversation and tool-call history was previously collected on demand by executing into live agent pods and reading runtime-specific files. That approach depended on pod availability, added latency to reads, and coupled the API to the filesystem formats of both runtimes. Agent Farm replaced it with Hermes and OpenClaw plugins that push events to an internal-only Ingest API, authenticated by a per-agent key generated at start.

## Considered alternative

Keep the pull model and continue reading runtime files through Kubernetes exec. This retained fewer moving parts inside the runtimes but preserved the availability, latency, and runtime-coupling problems.

## Consequences

- Ingest is a separate FastAPI application and internal service surface rather than a public product endpoint.
- Runtime plugins and API ingest DTOs share a telemetry contract.
- Starting an agent provisions its ingest key and telemetry configuration.
- Conversation and tool-call reads use persisted telemetry instead of reaching into a running pod.

Current behavior and source paths are documented in [`../features/activity-and-ingest.md`](../features/activity-and-ingest.md).
