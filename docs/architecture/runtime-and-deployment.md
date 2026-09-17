# Runtime and Deployment Architecture

## Read when

Read before changing Agent Restore Point Jobs, Hermes/OpenClaw behavior, agent Kubernetes resources, runtime images, telemetry configuration, Helm charts, deployment workflows, or service versions.

## Agent runtime assembly

Starting an agent is an API-orchestrated deployment flow:

1. Load the organization-owned agent and its pinned template version.
2. Render template Markdown with the agent identity.
3. Decrypt Agent Secrets used by tool Integrations; gateway-owned Communication Connection credentials stay in Communications, while enabled native Connection credentials are projected into the selected Agent runtime.
4. Select Hermes or OpenClaw runtime builders.
5. Combine explicitly assigned skills with eligible built-in provider skills.
6. Materialize aai-cli integrations and Google Workspace's gog artifacts from encrypted Agent Secrets.
7. Append tool pointers, integration policy, and unconditional runtime behaviour policies to rendered Markdown.
8. Generate fresh Ingest and Communications protocol credentials.
9. Build ConfigMap, Secret, PVC, Service, and Deployment resources, including the runtime-neutral communications adapter and any enabled native gateway configuration.
10. Apply resources through the Kubernetes client and mark the Agent running.

Runtime behaviour policies are appended to `AGENTS.md` rather than stored in a template, because both runtimes auto-load `AGENTS.md` into the startup system prompt. They are unconditional and carry no role-specific wording, so custom and forked templates inherit them and the role-scope policy defers to whatever role the agent's own template defines.

A Kubernetes/runtime start failure can place the Agent in `ERROR`; successful start clears the prior lifecycle error. Hermes and OpenClaw Deployments repair ownership of their root-mounted persistent state in a root init container before starting their non-root runtime, and pre-create Hermes' `workspace` subPath. Hermes base-image CI starts the real image against a fresh root-owned Docker volume, executes the generated init-container command as root, then proves the default `hermes` user can create the startup directories and write through the persistent workspace. Google Workspace runtime state is rebuilt by a ConfigMap-mounted `gog-setup.sh` from `GOG_*` Secret environment and is kept outside the persistent workspace. Connection validation and provider-session failures instead update that Communication Connection's observed health and do not change Agent lifecycle.

Command approval (the persisted `approval_mode` field) is mapped onto a runtime policy only for Hermes: `builders/hermes.py` maps `manual`→`manual`, `auto`→`smart`, and `off`→`off` into the Hermes `approvals.mode` config. OpenClaw has no user-configurable command-approval control — `build_openclaw_gateway_config` never receives or emits an approvals block — so the API rejects an explicit non-default `approval_mode` for an OpenClaw Agent instead of accepting and silently ignoring it. OpenClaw-specific command approval is tracked as a separate follow-up.

Alongside the mode, the generated config pins `approvals.timeout`, `approvals.cron_mode`, and `approvals.single_query_mode` to the pinned image's own defaults. This changes no behaviour today; it stops a runtime upgrade from moving the approval policy silently. `unattended_mode` is deliberately not emitted — v2026.8.19 does not read it, so writing it would be a no-op rather than an error. Headless approval policy therefore remains `deny`: a cron or heartbeat run that trips a dangerous-command gate is refused immediately rather than waiting out the timeout, because no human is present on those paths to answer. `BOOT.md` is the exception — it is driven through `/v1/runs` by `boot-run.py`, which the runtime treats as an interactive gateway session, so a flagged startup command parks awaiting an approval no one is watching for until the timeout denies it. Keeping startup work clear of flagged commands is the practical remedy. The image smoke test asserts each of these keys is still recognised, so an upgrade that renames one fails on the version bump rather than on a live Agent.

Hermes answers an approval with `always` by appending the pattern to root-level `command_allowlist` in its own `config.yaml`, which lives on the Agent PVC at `/opt/data/config.yaml`. `start.sh` therefore merges that file rather than copying over it: every settings-derived key is reasserted from the ConfigMap, and only `command_allowlist` is carried forward from the previous boot. The direction matters in both senses — copying over it revoked every permanent approval on each pod restart, while preserving the whole file would freeze an Agent on the model, approval mode, and plugin set it first started with, so a user could change a setting, receive a 200, restart, and observe nothing. The merge writes through a temporary file and renames, and any failure falls back to the original copy so a malformed persisted config cannot stop the runtime from booting.

An `always` grant is broader than it reads. For a dangerous-pattern finding Hermes stores the pattern rather than the command, so one grant approves the whole category — every `python3 -c`, `node -e` and `bash -c` after a single click on one of them — and the pinned image consults the allowlist before it branches on `approvals.mode`, so a grant made in `smart` would silence `manual` too. Manual mode therefore always asks. Grants live in an Agent Barn-owned file beside the config, `agentbarn-command-allowlist.json`, which each boot unions with anything Hermes wrote since; they are handed to Hermes only when the Agent is not in manual mode, and return when it leaves manual mode. The runtime adapter receives the mode as `APPROVAL_MODE` in the runtime Secret: in manual mode it offers only `once` and `deny`, and in every mode it accepts only an answer that was actually offered, so a typed `always` cannot create the grant the buttons withheld. The pinned endpoint itself accepts any of the four answers regardless of what it offered.

Progress visibility (the persisted `verbose_mode` field) is Hermes-only for a different reason: it isn't a missing config mapping, it's a missing transport. Hermes's `/v1/runs` API exposes mid-turn `tool.started`/`subagent.*` events over HTTP, which `communications-runtime-adapter.py` relays to chat only when `verbose_mode` is set. OpenClaw has the same kind of signal internally (`onAgentEvent` emits `"tool"`/`"thinking"`/`"item"` streams), but neither of its external HTTP surfaces (`/v1/chat/completions`, `/v1/responses`) forwards anything but the final assistant content and a terminal lifecycle event — there is no HTTP channel for the adapter to read progress from. Reaching parity needs an in-process OpenClaw plugin (same plugin SDK the shipped `telemetry-push` plugin uses) that bridges `onAgentEvent` progress out to Communications; until that exists, the API rejects `verbose_mode=true` for an OpenClaw Agent rather than accepting a setting with no effect. Tracked as the same follow-up as OpenClaw approval parity.

Hermes uses `/workspace` as its terminal and messaging working directory while its managed state remains under `/opt/data`. Agent Barn materializes assigned Skills under `/workspace/skills` and declares that directory in Hermes' `skills.external_dirs`, because the runtime's native discovery root is `/opt/data/skills`.

## Runtime-neutral communications

Both Hermes and OpenClaw consume the same versioned Communications protocol for gateway-owned Connections. A sidecar-style runtime adapter opens an authenticated, outbound Server-Sent Events control stream to Communications. A `delivery_available` wakeup makes the adapter claim durable inbound Communication Deliveries and invoke the runtime's local API with a Connection-scoped session key, submit the reply against the source delivery, and complete the delivery. OpenClaw uses its chat-completions endpoint; Hermes uses `/v1/runs` so command approvals and progress remain available. Inbound and outbound claim paths exclude Platforms configured as native, including stale Deliveries created before cutover. Native Connections receive provider credentials and transport configuration at Agent start on both runtimes. Because the shared adapter is copied into the Python 3.12 OpenClaw image and the Python 3.13 Hermes image, Ruff targets its source to Python 3.12 and a source-parse test guards the oldest image grammar.

Agent-initiated delivery uses the same Communications boundary. Interactive sends carry a server-issued token for the active inbound claim and are resolved only on that claim's Communication Connection; an interactive request cannot select the Agent's default or name a Connection. Scheduled final responses are captured into a durable SQLite spool and retried under one run identity until acknowledged, refused with a permanent 4xx, or about a day old; settled rows are pruned after seven days. On Hermes, a job created from a conversation retains its Connection/channel/thread origin, while startup-created work uses the Agent's one configured default. OpenClaw uses the default only when the completion has no recorded origin; its pinned cron hook exposes a delivery-channel label instead of the creating conversation, so unmappable completions are refused rather than diverted. The shared runtime client owns silence-marker filtering and destination parsing so Hermes and OpenClaw apply the same policy. Communications resolves and persists the destination before acknowledging acceptance, then the Platform Plugin revalidates current outbound policy before provider delivery. Only Slack currently advertises this capability.

For gateway-owned Hermes Agents, scheduled results are captured at a fenced scheduler side-effect boundary and native provider delivery is suppressed. For Hermes with a native Connection, `AGENTBARN_SCHEDULED_DELIVERY=0` disables that capture and the old spool drain for the whole runtime, so Hermes owns cron delivery on every Platform. OpenClaw captures scheduled results from its in-process `agent_end` hook; with a native Connection the same `AGENTBARN_SCHEDULED_DELIVERY=0` skips that capture and the spool drain, and OpenClaw delivers cron results to their origin or the Connection's `defaultTo`. Hermes also submits a non-empty `BOOT.md` through `/v1/runs` after the gateway becomes ready.

Each Hermes turn explicitly sends `resume_session: true` with the stable Connection/location/thread session identity. The Hermes base image carries `hermes-base/patch-run-session-history.py`: the pinned upstream endpoint otherwise persists under `session_id` but starts with empty history. The patch loads native SQLite conversation history, follows compaction lineage, preserves tool-call metadata, and fails on unavailable history storage instead of silently starting over. New sessions legitimately have empty history. Explicit caller-supplied history cannot be combined with resume mode. This requires deploying the patched Hermes image together with the adapter. Existing Hermes session data remains on the Agent PVC and becomes available again on the next turn; no database migration or transcript reconstruction is required. The image patch fails the build if its upstream source anchor changes.

Protocol version 2 replaces continuous idle claim polling with that persistent control stream. Redis Streams carry content-free, Agent-scoped delivery and cancellation wakeups between API replicas; PostgreSQL remains authoritative for claims, leases, idempotency, cancellation, and reconnect replay. The server takes a Redis cursor before emitting an unconditional replay wakeup, so commits before the cursor are found by the durable claim and commits after it are found in the stream. If Redis is unavailable, signal consumers use a bounded fallback wakeup to replay durable PostgreSQL state instead of dropping deliveries or browser updates. Existing version-1 claim/reply/complete routes remain accepted while already-running Agents are rebuilt. The runtime adapter retains a bounded five-second safety claim poll so a lost Redis wakeup cannot strand a durable Delivery, and applies bounded exponential reconnect backoff after either an unexpected error or a clean control-stream EOF so a closed stream cannot cause a hot reconnect loop. Claims last 120 seconds; Hermes renews its authenticated live claim every 60 seconds while an async run or approval is active, while OpenClaw retains the original bounded-turn lease behavior. Expired claims still use bounded retry and terminal failure feedback. Claim ordering and reply idempotency remain unchanged for both runtimes.

The runtime-control and Web Chat SSE responses use async body iterators, so an idle Redis stream read does not consume an AnyIO request-worker token. Web Chat's synchronous PostgreSQL reads are explicitly offloaded as short operations between signal waits.

Cancellation is durable before it is signalled. A cancelled source cannot enqueue a reply, and cancellation wins over a late successful runtime completion. A processing Delivery exposes `cancel_requested_at` immediately while its status remains `PROCESSING`, allowing Web Chat to stop showing it as awaiting a reply. The runtime adapter retains a bounded, expiring set of cancellation signals that arrive between claiming a Delivery and marking it in flight, closing that race without making Redis authoritative. OpenClaw's chat-completions request exposes no proven abort handle, so cancellation there is currently soft: local computation may finish, but its result is suppressed and the Delivery is terminally `CANCELLED`. Hermes's async `/v1/runs` model is not yet wired to this cancellation path. Agent pods expose no Communications control listener or admin Service port.

Runtime is persisted as `agent_type`. Platform is not an Agent field: an Agent may be headless or own any number of Communication Connections independently of whether Hermes or OpenClaw executes it.

## Platform Plugin boundary

Agent Barn ships a code-owned Platform Plugin registry. Each plugin owns typed settings and credential schemas, external validation, credential uniqueness/fingerprinting, inbound normalization/admission, optional best-effort inbound name enrichment, provider-session behavior, outbound sending, and optional processing-feedback hooks. Gateway-owned Slack uses supervised Socket Mode, Telegram uses supervised polling, and gateway-owned Discord uses a supervised Gateway session. When configured native, Slack and Discord instead run in the Agent pod on either runtime and are excluded from Communications supervision and Delivery claims. OpenClaw installs the `@openclaw/slack` and `@openclaw/discord` plugins from npm at its core version on first start, since only recorded npm installs get plugin state; its `agentbarn-observer` plugin reports content-free Journal stages and `healthz-server.js` reports channel health from `openclaw health`.

Adding a shipped platform adds one plugin and provider client plus focused tests. The generic Connection persistence, CRUD routes, schema-driven UI, durable delivery pipeline, runtime protocol, and Agent builders do not gain platform branches. Plugins are trusted release artifacts, not dynamically installed packages.

Connection credentials are encrypted and never returned by read APIs. Communication Connection CRUD is subordinate to Agent visibility and Permissions. Connection revision changes cause the gateway supervisor to reconcile the provider session without restarting the Agent.

## Mention gating

Shared-room admission is a Platform Plugin concern. Plugin settings define provider-specific restrictions. Discord exposes Hermes' native user, role, and channel gates plus an explicit Allow all users switch. A user allowlist applies in DMs and server messages; channel and role gates apply in server messages. There are no separate guild or DM policy switches. Native Hermes receives those gates directly and owns Discord admission; native OpenClaw receives them as a wildcard `guilds["*"]` entry (users, roles, channels) plus a DM `allowFrom`. The Agent Barn observer is telemetry-only on both. Slack channel messages require a direct bot mention and expose a schema-driven thread policy: `every_message` requires a mention on every thread reply, while `start_only` admits unmentioned replies only after a matching Connection-scoped thread has persisted Agent state. Slack captures the bot user identity at ingress, ignores duplicate `app_mention` events in favor of `message` events, and applies DM/allowlist checks before mention admission. Durable ownership is supplied to plugins through the Communications admission seam; it is never process-local. Updating a native Connection restarts a running Agent because its credentials and policy are projected only at boot; gateway-owned changes reconcile the supervisor session without rebuilding the runtime.

## Processing feedback

Processing feedback is a best-effort Platform Plugin capability, separate from durable Communication Delivery state. Communications invokes the provider-neutral lifecycle seam after an inbound delivery is accepted, when runtime processing is claimed, and after terminal success or failure is known. Slack reacts with 👀 on acceptance, shows `assistant.threads.setStatus` while the runtime works, and replaces the acknowledgement with ✅ only after outbound provider delivery succeeds or ❌ after terminal failure. Slack lifecycle reactions target the canonical provider message timestamp, while status targets the conversation thread. On terminal runtime failure, Discord, Telegram, and Teams reply in the originating conversation with the same safe normalized reason; Telegram uses the source message's reply parameters, and Teams reuses the inbound activity's stored service/conversation routing. Slack, Discord, Telegram, and Teams feedback calls are best-effort and safe to retry; failures are bounded warnings and never change delivery retry or completion state. The built-in Web Chat adapter does not post a second provider notice; its read model exposes the durable safe error summary so the dashboard renders the same guidance. A normalized runtime failure marked non-retryable, including HTTP 402 provider credit or billing failures, transitions directly to `DEAD_LETTERED`; other failures retain bounded retry behavior. Plugins without this capability no-op.

## Connection failure recovery

The gateway supervisor isolates provider ingress per enabled Connection and coordinates replicas with database leases. Only Connections that declare provider ingress (supervised or webhook) enter the ingress task set; the built-in Web Chat Connection declares neither and does not acquire a lease or parked task. Setup and session failures set Connection health to `ERROR` and retry without altering Agent lifecycle; a capability-less or unimplemented supervised ingress fails closed as `DEGRADED`. An authorized Agent update can request one reconnect, which increments the Connection revision so the supervisor cancels and recreates that provider session. Webhook Connections are marked connected after configuration is loaded, while authenticated provider requests remain independently validated. Connection and Delivery transitions are retained in the content-free Communications operation journal; ingress refuses to acknowledge a provider event when its observation or policy decision cannot be journaled. Error codes and summaries are allowlisted/redacted both when written and when projected from legacy rows. The supervisor prunes journal rows older than `COMMUNICATION_JOURNAL_RETENTION_DAYS` (default 31). Outbound claims preserve per-conversation order, and each retry reuses the durable Delivery's stable provider idempotency key. The Communications metrics endpoint refreshes low-cardinality status, queue, latency, outcome, reconnect, and policy-disposition metrics from the durable rows.

## Hermes scheduled-run context

Hermes scheduled runs are isolated sessions: they do not inherit Slack thread or interactive-session history unless a job explicitly supplies continuity context. They do load the agent's persistent `MEMORY.md` and `USER.md` stores into the system prompt, using the same enabled memory configuration as interactive runs. This contract requires Hermes `v2026.8.19` or newer and is verified inside the pinned base image because an API-side builder test alone cannot prove runtime behavior.

Cron delivery is automatic. When a scheduled run has nothing actionable to deliver, its final response must be a recognized silence marker (`[SILENT]`, `SILENT`, `NO_REPLY`, `NO REPLY`, or `HEARTBEAT_OK`); ordinary prose such as `Nothing to flag today.` is a deliverable message, not a private acknowledgement.

## Telemetry and costs

Agent runtimes report messages and tool-call state to the separate Ingest API using the per-start ingest key. Ingest authentication currently remains valid after stop because status is not checked and the stored key is not cleared. Costs follow a separate path: a CronJob syncs LiteLLM's spend log into the `cost_record` table every 15 minutes, attributes each row through each agent's LiteLLM key identity, and recovers costs LiteLLM failed to record by asking OpenRouter what it charged. The API reads that table, not the proxy.

## Service deployment

`../../helmfile.yaml.gotmpl` orders PostgreSQL releases, LiteLLM, API, UI, and the monitoring stack. The API chart deploys separate product, Ingest, and Communications processes; the Communications Service is reachable internally by runtimes and exposes only the provider-webhook prefix through ingress. API deployment mounts Kubernetes access so the product service can manage Agent resources. An API Helm hook runs Alembic before installation or upgrade.

The API image also runs Domain Event delivery workloads with different commands: a Dramatiq worker deployment processes committed Event Delivery IDs from Redis, and a CronJob runs the one-shot Event Delivery reconciler. Communications uses PostgreSQL-backed leases and durable Communication Deliveries, distinct from Domain Event delivery.

The k3s deploy workflow builds API and UI images under moving environment tags, passes those tags into Helmfile as `API_IMAGE_TAG` and `UI_IMAGE_TAG`, and applies Helmfile. The current convention is `latest` on `main` and `latest-staging` on the `staging` branch. Component change detection compares the current commit with the latest successful deploy run for that branch; failed runs therefore leave their entire source range pending for the next attempt. Manual dispatches and missing or non-ancestor baselines rebuild all components. Manual and bundled release flows also pass explicit API/UI tags; chart metadata is not used as the source of truth for API/UI images.

Hosted public production is a separate workflow (`.github/workflows/deploy-public.yml`) that runs only on `vX.Y.Z` tags, pushes those tags to `registry.agentbarn.dev`, and helmfile-syncs the Talos cluster. k3s remains the AAI Labs testing ground. See [`../guidelines/operations.md`](../guidelines/operations.md#public-cluster-talos) and [`../adr/2026-08-27-public-cluster-release-tags.md`](../adr/2026-08-27-public-cluster-release-tags.md).

Every release's namespace and `needs:` entries are templated on a `NAMESPACE` env var (default `agent-farm`), which is how the `staging` branch deploys a fully separate stack into `agent-farm-staging` instead of prod's `agent-farm`. See [`../guidelines/operations.md`](../guidelines/operations.md#staging-environment) for the operator runbook and [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why namespace isolation was chosen over GitHub Environments or a second cluster. The public cluster also uses `NAMESPACE=agent-farm`; isolation from k3s is the cluster boundary, not a third namespace name.

## Observability

`../../helm/monitoring/` deploys namespace-scoped Prometheus, Grafana, and Alertmanager charts. The product API exposes platform probes on `:8000`, Ingest exposes telemetry metrics on `:8001`, and Communications exposes HTTP metrics on `:8002`; LiteLLM and Agent health services retain their existing scrape targets. Alert rules route through Alertmanager, and Grafana dashboards are provisioned from chart ConfigMaps.

## Restore point Jobs

Capture and restore run as `batch/v1` Jobs rather than pods managed by the API, and reuse the
API's own image so the archive logic and its exclusion sets are always the same build as the
API that scheduled them — `API_IMAGE` is rendered from the same chart expression as the API
container's `image`. Nothing new is built or published.

Both mount the Agent's `agent-<uuid>` PVC, which is why they require a stopped Agent: the
volume is ReadWriteOnce and cannot be held by the Agent pod and a Job pod at once. Capture
mounts the Agent volume read-only alongside a fresh per-restore-point PVC. Restore mounts
three — the Agent volume writable, the new Pre-Restore destination, and the chosen archive
read-only — and performs the safety-net capture and the extraction in one process, so the
backup is on disk before anything is wiped.

The Job runs as root. Extraction then applies the ownership the target volume already had,
read before the wipe, because the two runtimes differ: Hermes' init container chowns `/opt/data`
recursively, while OpenClaw's chowns only the mount point, so a restore cannot rely on the next
start to repair ownership.

The API learns each Job's outcome by reading its status, and its archive manifest by reading
the Job pod's logs — the manifest is written onto the restore point's PVC, which the API cannot
mount. Distinct exit codes separate a failed safety-net capture, where the Agent volume was
never touched, from a failed extraction, where it was.

CSI `VolumeSnapshot` is deliberately unused; see
[`../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md).

## Kubernetes client constraint

Kubernetes `stream()` and `portforward()` temporarily monkey-patch `ApiClient.request` while establishing WebSocket connections. They use a dedicated `CoreV1Api` and `ApiClient` so concurrent REST operations cannot hit the patched handler; keep streaming and ordinary CRUD clients isolated.

## Source map

| Concern                         | Source                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Runtime orchestration           | `../../api/domains/agents/service.py`                                                 |
| Ingest process and routing      | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                       |
| Communications process and routing | `../../api/communications_app.py`, `../../api/communications_main.py`, `../../api/domains/communications/` |
| Domain Event delivery workers   | `../../api/worker_app.py`, `../../api/domains/events/worker.py`, `../../api/domains/events/reconciliation.py`, `../../helm/agentbarn-api/templates/event-delivery-worker-deployment.yaml`, `../../helm/agentbarn-api/templates/event-delivery-reconciliation-cronjob.yaml` |
| Shared Kubernetes builders      | `../../api/domains/agents/builders/common.py`                                         |
| Hermes builders                 | `../../api/domains/agents/builders/hermes.py`, `../../hermes-base/`                         |
| OpenClaw builders               | `../../api/domains/agents/builders/openclaw.py`, `../../openclaw-base/`                     |
| Skill and integration artifacts | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`, `../../api/domains/agents/gog_artifacts.py` |
| Provider clients                | `../../api/infrastructure/slack/`, `../../api/infrastructure/telegram/`, `../../api/infrastructure/discord/` |
| Kubernetes client               | `../../api/infrastructure/kubernetes/`                                                |
| Charts and release ordering     | `../../helm/`, `../../helmfile.yaml.gotmpl`                                                 |
| Deployment workflow             | `../../.github/workflows/deploy.yml` (k3s), `../../.github/workflows/deploy-public.yml` (Talos public) |
| Monitoring stack                | `../../helm/monitoring/`                                                               |
| API metrics                     | `../../api/core/metrics.py`, `../../api/domains/communications/metrics.py`             |

## Change impact

Runtime changes must be checked against both runtime builders, images/base configuration, Agent lifecycle tests, telemetry, and the versioned Communications protocol. Platform changes belong at the Platform Plugin seam and require plugin, gateway, Connection CRUD/schema, and delivery tests rather than runtime branches. Chart template/value changes require the chart `version` bump according to `../../AGENTS.md`.
