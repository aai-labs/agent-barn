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
11. Record the runtime configuration digest the pod was built from.

Runtime behaviour policies are appended to `AGENTS.md` rather than stored in a template, because both runtimes auto-load `AGENTS.md` into the startup system prompt. They are unconditional and carry no role-specific wording, so custom and forked templates inherit them and the role-scope policy defers to whatever role the agent's own template defines.

A Kubernetes/runtime start failure can place the Agent in `ERROR`; successful start clears the prior lifecycle error. Hermes and OpenClaw Deployments repair ownership of their root-mounted persistent state in a root init container before starting their non-root runtime, and pre-create Hermes' `workspace` subPath. Hermes base-image CI starts the real image against a fresh root-owned Docker volume, executes the generated init-container command as root, then proves the default `hermes` user can create the startup directories and write through the persistent workspace. Google Workspace runtime state is rebuilt by a ConfigMap-mounted `gog-setup.sh` from `GOG_*` Secret environment and is kept outside the persistent workspace. Connection validation and provider-session failures instead update that Communication Connection's observed health and do not change Agent lifecycle.

Command approval (the persisted `approval_mode` field) is mapped onto a runtime policy only for Hermes: `builders/hermes.py` maps `manual`→`manual`, `auto`→`smart`, and `off`→`off` into the Hermes `approvals.mode` config. OpenClaw has no user-configurable command-approval control — `build_openclaw_gateway_config` never receives or emits an approvals block — so the API rejects an explicit non-default `approval_mode` for an OpenClaw Agent instead of accepting and silently ignoring it. OpenClaw-specific command approval is tracked as a separate follow-up.

Alongside the mode, the generated config pins `approvals.timeout`, `approvals.cron_mode`, and `approvals.single_query_mode` to the pinned image's own defaults. This changes no behaviour today; it stops a runtime upgrade from moving the approval policy silently. `unattended_mode` is deliberately not emitted — v2026.8.19 does not read it, so writing it would be a no-op rather than an error. Headless approval policy therefore remains `deny`: a cron or heartbeat run that trips a dangerous-command gate is refused immediately rather than waiting out the timeout, because no human is present on those paths to answer. `BOOT.md` is the exception — it is driven through `/v1/runs` by `boot-run.py`, which the runtime treats as an interactive gateway session, so a flagged startup command parks awaiting an approval no one is watching for until the timeout denies it. Keeping startup work clear of flagged commands is the practical remedy. The image smoke test asserts each of these keys is still recognised, so an upgrade that renames one fails on the version bump rather than on a live Agent.

Hermes answers an approval with `always` by appending the pattern to root-level `command_allowlist` in its own `config.yaml`, which lives on the Agent PVC at `/opt/data/config.yaml`. `start.sh` therefore merges that file rather than copying over it: every settings-derived key is reasserted from the ConfigMap, and only `command_allowlist` is carried forward from the previous boot. The direction matters in both senses — copying over it revoked every permanent approval on each pod restart, while preserving the whole file would freeze an Agent on the model, approval mode, and plugin set it first started with, so a user could change a setting, receive a 200, restart, and observe nothing. The merge writes through a temporary file and renames, and any failure falls back to the original copy so a malformed persisted config cannot stop the runtime from booting.

An `always` grant is broader than it reads. For a dangerous-pattern finding Hermes stores the pattern rather than the command, so one grant approves the whole category — every `python3 -c`, `node -e` and `bash -c` after a single click on one of them — and the pinned image consults the allowlist before it branches on `approvals.mode`, so a grant made in `smart` would silence `manual` too. Manual mode therefore always asks. Grants live in an Agent Barn-owned file beside the config, `agentbarn-command-allowlist.json`, which each boot unions with anything Hermes wrote since; they are handed to Hermes only when the Agent is not in manual mode, and return when it leaves manual mode. The runtime adapter receives the mode as `APPROVAL_MODE` in the runtime Secret: in manual mode it offers only `once` and `deny`, and in every mode it accepts only an answer that was actually offered, so a typed `always` cannot create the grant the buttons withheld. The pinned endpoint itself accepts any of the four answers regardless of what it offered.

Progress visibility (the persisted `verbose_mode` field) is Hermes-only for a different reason: it isn't a missing config mapping, it's a missing transport. Hermes's `/v1/runs` API exposes mid-turn `tool.started`/`subagent.*` events over HTTP, which `communications-runtime-adapter.py` relays to chat only when `verbose_mode` is set. OpenClaw has the same kind of signal internally (`onAgentEvent` emits `"tool"`/`"thinking"`/`"item"` streams), but neither of its external HTTP surfaces (`/v1/chat/completions`, `/v1/responses`) forwards anything but the final assistant content and a terminal lifecycle event — there is no HTTP channel for the adapter to read progress from. Reaching parity needs an in-process OpenClaw plugin (same plugin SDK the shipped `telemetry-push` plugin uses) that bridges `onAgentEvent` progress out to Communications; until that exists, the API rejects `verbose_mode=true` for an OpenClaw Agent rather than accepting a setting with no effect. Tracked as the same follow-up as OpenClaw approval parity.

Hermes uses `/workspace` as its terminal and messaging working directory while its managed state remains under `/opt/data`. Agent Barn materializes assigned Skills under `/workspace/skills` and declares that directory in Hermes' `skills.external_dirs`, because the runtime's native discovery root is `/opt/data/skills`.

### Runtime configuration digest

Both runtimes read their configuration once, at container start, so a pod keeps serving the code and images it was assembled from until someone restarts it. Step 11 records that fact. `Agent.running_config_digest` identifies the platform code and runtime images the pod was built from, and `AgentRead.update_available` reports when a running Agent's recorded digest differs from what the API would build now. Stop clears the digest, because a stopped Agent has no pod to describe. The signal is advisory: it blocks no operation, changes no Agent behaviour, and clears on the next start. See [`../features/agents.md`](../features/agents.md) for the read contract.

The watched set is computed, never curated. `runtime_digest.py` walks the static closure of `AgentService._provision_and_start` with `ast`, following three kinds of edge: `self._method()` calls within `AgentService`, `self.<collaborator>.<method>()` resolved through the class-level annotations that declare each injected collaborator, and every free name to its defining module. It collects individual definitions rather than whole files, so editing an unrelated DTO in a shared module registers nothing while editing a reachable one does. A hand-written list was measured against this closure before the design settled and covered roughly a third of it, silently omitting `skills.models.derive_tools_pointer`, `agent_settings.lookup.resolve_default_model`, `google_workspace_scopes.required_service_scopes` and the credential content schemas among others — which is why nothing here is maintained by hand and no version constant exists to bump.

Resolution must follow re-export barrels and relative imports. `build_config_map` resolves to the `builders` package rather than to `builders/openclaw.py`, and that package re-exports with `from .openclaw import ...`. Skipping either step silently drops the runtime builders — the largest single source of agent configuration — out of the closure, so the unit test asserts their presence rather than trusting the walk.

Python is normalised through `ast.dump` with docstrings stripped, so comments, blank lines, `ruff format` output, and CRLF checkouts leave the digest unchanged while string literals — the policy text itself — move it. Two asset roots are hashed as bytes instead, because the builders read them from disk into module-level constants where AST analysis cannot see their content: `domains/agents/scripts/` and `domains/agents/aai_cli_skills/bundled/`. Runtime image identity comes from `Config.openclaw_image` and `Config.hermes_image`, which are environment rather than files; the API image copies only `api/`, so the base-image `VERSION` files do not exist at runtime. The digest is computed once at import and cached, because the Agent read that consumes it runs per Agent in list responses.

Known limits fall in both directions, and which is which matters.

These **under-report** — a real change that the digest does not move:

- **Mutable image tags.** The digest folds in the image *reference*, not its content, so rebuilding and pushing the same tag (`:dev`, `:latest`) leaves it unchanged. Immutable or digest-pinned tags do not have this problem.
- **Deployment environment beyond the two image references.** `ingest_base_url`, `communications_base_url`, and the Firecrawl settings are read at start but excluded, because a curated `Config` subset would reintroduce exactly the hand-maintained list this design exists to avoid.
- **Dynamic dispatch and runtime registration** are invisible to static analysis. The assembly path uses neither today, and introducing one edits a call site that is itself inside the closure, so it registers once.

These **over-report** — the digest moves without a behavioural change:

- The two asset roots are compared byte for byte, so a comment-only edit to `start.sh` or `init-openclaw.js` moves the digest. Shell and JavaScript cannot be normalised the way Python can.
- `Agent` is inside the closure, so adding any column to that table moves the digest once.
- A Python minor-version upgrade can change `ast.dump` output, moving the digest once across the fleet.

Over-reporting is the safe direction: the prompt is advisory, and a restart preserves the PVC, conversation history, Communication Connections, and Hermes `always` grants, rebuilding only the ConfigMap, Secret, and per-start credentials. The under-reporting cases are the ones to watch, because an Agent silently keeps serving older behaviour.

The collaborator walk is transitive in both dimensions: it follows `self._method()` calls *within* each injected collaborator, not only the methods the assembly path calls directly. Without that, helpers such as `KubernetesClient._create_or_get` — which decides whether a 409 reuses an existing resource — would change provisioning without moving the digest.

## Runtime-neutral communications

Both Hermes and OpenClaw consume the same versioned Communications protocol for gateway-owned Connections. A sidecar-style runtime adapter opens an authenticated, outbound Server-Sent Events control stream to Communications. A `delivery_available` wakeup makes the adapter claim durable inbound Communication Deliveries and invoke the runtime's local API with a Connection-scoped session key, submit the reply against the source delivery, and complete the delivery. OpenClaw uses its chat-completions endpoint; Hermes uses `/v1/runs` so command approvals and progress remain available. Inbound and outbound claim paths exclude Platforms configured as native, including stale Deliveries created before cutover. Native Connections receive provider credentials and transport configuration at Agent start on both runtimes. Because the shared adapter is copied into the Python 3.12 OpenClaw image and the Python 3.13 Hermes image, Ruff targets its source to Python 3.12 and a source-parse test guards the oldest image grammar.

Agent Webhook triggers use a separate immediate path. The product API calls an authenticated private listener on port 8082 of the target Agent Service; it does not create a Communication Delivery or wait for a runtime claim. The listener durably deduplicates the dispatch generation on the Agent volume, creates or recovers a deterministic one-shot job in the native Hermes/OpenClaw scheduler, and returns `202` only after the scheduler accepts the run. Hermes/OpenClaw then owns execution and final delivery through the selected native Slack, Discord, Telegram, or Teams configuration. Agent Barn records submission success or failure only and receives no execution callback.

Agent-initiated delivery uses the same Communications boundary. Interactive sends carry a server-issued token for the active inbound claim and are resolved only on that claim's Communication Connection; an interactive request cannot select the Agent's default or name a Connection. Scheduled final responses are captured into a durable SQLite spool and retried under one run identity until acknowledged, refused with a permanent 4xx, or about a day old; settled rows are pruned after seven days. On Hermes, a job created from a conversation retains its Connection/channel/thread origin, while startup-created work uses the Agent's one configured default. OpenClaw uses the default only when the completion has no recorded origin; its pinned cron hook exposes a delivery-channel label instead of the creating conversation, so unmappable completions are refused rather than diverted. The shared runtime client owns silence-marker filtering and destination parsing so Hermes and OpenClaw apply the same policy. Communications resolves and persists the destination before acknowledging acceptance, then the Platform Plugin revalidates current outbound policy before provider delivery. Only Slack currently advertises this capability.

For gateway-owned Hermes Agents, scheduled results are captured at a fenced scheduler side-effect boundary and native provider delivery is suppressed. For Hermes with a native Connection, `AGENTBARN_SCHEDULED_DELIVERY=0` disables that capture and the old spool drain for the whole runtime, so Hermes owns cron delivery on every Platform. OpenClaw captures scheduled results from its in-process `agent_end` hook; with a native Connection the same `AGENTBARN_SCHEDULED_DELIVERY=0` skips that capture and the spool drain, and OpenClaw delivers cron results to their origin or the Connection's `defaultTo`. Hermes also submits a non-empty `BOOT.md` through `/v1/runs` after the gateway becomes ready.

Each Hermes turn explicitly sends `resume_session: true` with the stable Connection/location/thread session identity. The Hermes base image carries `hermes-base/patch-run-session-history.py`: the pinned upstream endpoint otherwise persists under `session_id` but starts with empty history. The patch loads native SQLite conversation history, follows compaction lineage, preserves tool-call metadata, and fails on unavailable history storage instead of silently starting over. New sessions legitimately have empty history. Explicit caller-supplied history cannot be combined with resume mode. This requires deploying the patched Hermes image together with the adapter. Existing Hermes session data remains on the Agent PVC and becomes available again on the next turn; no database migration or transcript reconstruction is required. The image patch fails the build if its upstream source anchor changes.

Protocol version 2 replaces continuous idle claim polling with that persistent control stream. Redis Streams carry content-free, Agent-scoped delivery and cancellation wakeups between API replicas; PostgreSQL remains authoritative for claims, leases, idempotency, cancellation, and reconnect replay. The server takes a Redis cursor before emitting an unconditional replay wakeup, so commits before the cursor are found by the durable claim and commits after it are found in the stream. If Redis is unavailable, signal consumers use a bounded fallback wakeup to replay durable PostgreSQL state instead of dropping deliveries or browser updates. Existing version-1 claim/reply/complete routes remain accepted while already-running Agents are rebuilt. The runtime adapter retains a bounded five-second safety claim poll so a lost Redis wakeup cannot strand a durable Delivery, and applies bounded exponential reconnect backoff after either an unexpected error or a clean control-stream EOF so a closed stream cannot cause a hot reconnect loop. Claims last 120 seconds; Hermes renews its authenticated live claim every 60 seconds while an async run or approval is active, while OpenClaw retains the original bounded-turn lease behavior. Expired claims still use bounded retry and terminal failure feedback. Claim ordering and reply idempotency remain unchanged for both runtimes.

The runtime-control and Web Chat SSE responses use async body iterators, so an idle Redis stream read does not consume an AnyIO request-worker token. Web Chat's synchronous PostgreSQL reads are explicitly offloaded as short operations between signal waits.

Cancellation is durable before it is signalled. A cancelled source cannot enqueue a reply, and cancellation wins over a late successful runtime completion. A processing Delivery exposes `cancel_requested_at` immediately while its status remains `PROCESSING`, allowing Web Chat to stop showing it as awaiting a reply. The runtime adapter retains a bounded, expiring set of cancellation signals that arrive between claiming a Delivery and marking it in flight, closing that race without making Redis authoritative. OpenClaw's chat-completions request exposes no proven abort handle, so cancellation there is currently soft: local computation may finish, but its result is suppressed and the Delivery is terminally `CANCELLED`. Hermes's async `/v1/runs` model is not yet wired to this cancellation path. Agent pods expose no Communications control listener or admin Service port.

Runtime is persisted as `agent_type`. Platform is not an Agent field: an Agent may be headless or own any number of Communication Connections independently of whether Hermes or OpenClaw executes it.

## Platform Plugin boundary

Agent Barn ships a code-owned Platform Plugin registry. Each plugin owns typed settings and credential schemas, external validation, credential uniqueness/fingerprinting, inbound normalization/admission, optional best-effort inbound name enrichment, provider-session behavior, outbound sending, and optional processing-feedback hooks. Gateway-owned Slack uses supervised Socket Mode, Telegram uses supervised polling, and gateway-owned Discord uses a supervised Gateway session. When configured native, Slack, Discord, Telegram, and Teams instead run in the Agent pod on either runtime and are excluded from Communications Delivery claims. Teams is webhook-based: the product API owns the stable public Connection route, verifies the Bot Framework JWT and enforces Connection policy, then relays the raw activity and Authorization header to port 3978 on the Agent's private ClusterIP Service; it passes the runtime's HTTP response back to Bot Framework so native `invoke` responses continue to work without depending on the Communications deployment. OpenClaw installs the `@openclaw/slack`, `@openclaw/discord`, and `@openclaw/msteams` plugins from npm at its core version on first start, since only recorded npm installs get plugin state, and uses the Telegram channel bundled in its core; its `agentbarn-observer` plugin reports content-free Journal stages and `healthz-server.js` reports channel health from `openclaw health`.

Adding a shipped platform adds one plugin and provider client plus focused tests. The generic Connection persistence, CRUD routes, schema-driven UI, durable delivery pipeline, runtime protocol, and Agent builders do not gain platform branches. Plugins are trusted release artifacts, not dynamically installed packages.

Connection credentials are encrypted and never returned by read APIs. Communication Connection CRUD is subordinate to Agent visibility and Permissions. Connection revision changes cause the gateway supervisor to reconcile the provider session without restarting the Agent.

## Mention gating

Shared-room admission is a Platform Plugin concern. Plugin settings define provider-specific restrictions. Discord exposes Hermes' native user, role, and channel gates plus an explicit Allow all users switch. A user allowlist applies in DMs and server messages; channel and role gates apply in server messages. There are no separate guild or DM policy switches. Native Hermes receives those gates directly and owns Discord admission; native OpenClaw receives them as a wildcard `guilds["*"]` entry (users, roles, channels) plus a DM `allowFrom`. The Agent Barn observer is telemetry-only on both. Native Telegram keeps the DM and group policies and requires a mention or reply to the bot in groups, never in DMs; gateway-owned Telegram does not mention-gate. Runtime-owned Teams keeps policy enforcement at the authenticated public relay because the runtimes must accept the activity unchanged for Bot Framework lifecycle and Adaptive Card handling. Slack channel messages require a direct bot mention and expose a schema-driven thread policy: `every_message` requires a mention on every thread reply, while `start_only` admits unmentioned replies only after a matching Connection-scoped thread has persisted Agent state. Slack captures the bot user identity at ingress, ignores duplicate `app_mention` events in favor of `message` events, and applies DM/allowlist checks before mention admission. Durable ownership is supplied to plugins through the Communications admission seam; it is never process-local. Updating a native Connection restarts a running Agent because its credentials and policy are projected only at boot; gateway-owned changes reconcile the supervisor session without rebuilding the runtime.

## Processing feedback

Processing feedback is a best-effort Platform Plugin capability, separate from durable Communication Delivery state. Communications invokes the provider-neutral lifecycle seam after an inbound delivery is accepted, when runtime processing is claimed, and after terminal success or failure is known. Slack reacts with 👀 on acceptance, shows `assistant.threads.setStatus` while the runtime works, and replaces the acknowledgement with ✅ only after outbound provider delivery succeeds or ❌ after terminal failure. Slack lifecycle reactions target the canonical provider message timestamp, while status targets the conversation thread. On terminal runtime failure, Discord, Telegram, and Teams reply in the originating conversation with the same safe normalized reason; Telegram uses the source message's reply parameters, and Teams reuses the inbound activity's stored service/conversation routing. Slack, Discord, Telegram, and Teams feedback calls are best-effort and safe to retry; failures are bounded warnings and never change delivery retry or completion state. The built-in Web Chat adapter does not post a second provider notice; its read model exposes the durable safe error summary so the dashboard renders the same guidance. A normalized runtime failure marked non-retryable, including HTTP 402 provider credit or billing failures, transitions directly to `DEAD_LETTERED`; other failures retain bounded retry behavior. Plugins without this capability no-op.

## Connection failure recovery

The gateway supervisor isolates provider ingress per enabled Connection and coordinates replicas with database leases. Only Connections that declare provider ingress (supervised or webhook) enter the ingress task set; the built-in Web Chat Connection declares neither and does not acquire a lease or parked task. Setup and session failures set Connection health to `ERROR` and retry without altering Agent lifecycle; a capability-less or unimplemented supervised ingress fails closed as `DEGRADED`. An authorized Agent update can request one reconnect, which increments the Connection revision so the supervisor cancels and recreates that provider session. Webhook Connections are marked connected after configuration is loaded, while authenticated provider requests remain independently validated. Connection and Delivery transitions are retained in the content-free Communications operation journal; ingress refuses to acknowledge a provider event when its observation or policy decision cannot be journaled. Error codes and summaries are allowlisted/redacted both when written and when projected from legacy rows. The supervisor prunes journal rows older than `COMMUNICATION_JOURNAL_RETENTION_DAYS` (default 31). Outbound claims preserve per-conversation order, and each retry reuses the durable Delivery's stable provider idempotency key. The Communications metrics endpoint refreshes low-cardinality status, queue, latency, outcome, reconnect, and policy-disposition metrics from the durable rows.

## Hermes scheduled-run context

Hermes scheduled runs are isolated sessions: they do not inherit Slack thread or interactive-session history unless a job explicitly supplies continuity context. They do load the agent's persistent `MEMORY.md` and `USER.md` stores into the system prompt, using the same enabled memory configuration as interactive runs. This contract requires Hermes `v2026.8.19` or newer and is verified inside the pinned base image because an API-side builder test alone cannot prove runtime behavior.

Hermes Agents have two intentional writable mounts: `/opt/data` for Hermes-owned
state and `/workspace` for the persistent Agent workspace. The base image sets
`HERMES_WRITE_SAFE_ROOT=/opt/data:/workspace`, so Hermes' file tools may write
only under those roots; the image smoke test pins both the allowed and denied
paths. Agents pick this up when they run a base image at `0.2.4` or newer.
Hermes' curated `USER.md` and `MEMORY.md` live under
`/opt/data/memories/`; daily notes written as `memory/YYYY-MM-DD.md` remain
workspace files under `/workspace`.

OpenClaw has no ambient model-backed heartbeat: Agent Barn writes
`agents.defaults.heartbeat.every: "0m"` and `target: "none"` on every start,
so only explicit Agent cron jobs initiate proactive work. The OpenClaw startup
script replaces this policy rather than inheriting an older PVC-held value. A
pre-2026.8 workspace is detected from its runtime-owned state markers and is
migrated once with non-interactive `openclaw doctor --fix` before the gateway
starts, after the config and plugin directories are prepared so doctor validates
the config Agent Barn just wrote; healthy workspaces never run the broad doctor
repair during startup. A failed migration is logged and does not stop startup.

Cron delivery is automatic. When a scheduled run has nothing actionable to deliver, its final response must be a recognized silence marker (`[SILENT]`, `SILENT`, `NO_REPLY`, `NO REPLY`, or `HEARTBEAT_OK`); ordinary prose such as `Nothing to flag today.` is a deliverable message, not a private acknowledgement.

## Telemetry and costs

Agent runtimes report messages and tool-call state to the separate Ingest API using the per-start ingest key. Ingest authentication currently remains valid after stop because status is not checked and the stored key is not cleared. Costs follow a separate path: a CronJob syncs LiteLLM's spend log into the `cost_record` table every 15 minutes, attributes each row through each agent's LiteLLM key identity, and recovers costs LiteLLM failed to record by asking OpenRouter what it charged. The API reads that table, not the proxy.

## Service deployment

`../../helmfile.yaml.gotmpl` orders PostgreSQL releases, LiteLLM, Honcho, API, UI, and the monitoring stack. The API chart deploys separate product, Ingest, and Communications processes; the Communications Service is reachable internally by runtimes and exposes only the provider-webhook prefix through ingress. API deployment mounts Kubernetes access so the product service can manage Agent resources. An API Helm hook runs Alembic before installation or upgrade.

The API image also runs Domain Event delivery workloads with different commands: a Dramatiq worker deployment processes committed Event Delivery IDs from Redis, and a CronJob runs the one-shot Event Delivery reconciler. Communications uses PostgreSQL-backed leases and durable Communication Deliveries, distinct from Domain Event delivery.

The k3s deploy workflow builds API and UI images under moving environment tags, passes those tags into Helmfile as `API_IMAGE_TAG` and `UI_IMAGE_TAG`, and applies Helmfile. The current convention is `latest` on `main` and `latest-staging` on the `staging` branch. Component change detection compares the current commit with the latest successful deploy run for that branch; failed runs therefore leave their entire source range pending for the next attempt. Manual dispatches and missing or non-ancestor baselines rebuild all components. Manual and bundled release flows also pass explicit API/UI tags; chart metadata is not used as the source of truth for API/UI images.

Hosted public production is a separate workflow (`.github/workflows/deploy-public.yml`) that runs only on `vX.Y.Z` tags, pushes those tags to `registry.agentbarn.dev`, and helmfile-syncs the Talos cluster. k3s remains the AAI Labs testing ground. See [`../guidelines/operations.md`](../guidelines/operations.md#public-cluster-talos) and [`../adr/2026-08-27-public-cluster-release-tags.md`](../adr/2026-08-27-public-cluster-release-tags.md).

Every release's namespace and `needs:` entries are templated on a `NAMESPACE` env var (default `agent-farm`), which is how the `staging` branch deploys a fully separate stack into `agent-farm-staging` instead of prod's `agent-farm`. See [`../guidelines/operations.md`](../guidelines/operations.md#staging-environment) for the operator runbook and [`../adr/2026-07-13-staging-environment-namespace-isolation.md`](../adr/2026-07-13-staging-environment-namespace-isolation.md) for why namespace isolation was chosen over GitHub Environments or a second cluster. The public cluster also uses `NAMESPACE=agent-farm`; isolation from k3s is the cluster boundary, not a third namespace name.

## Honcho memory service

Honcho is an optional memory backend for Agents, deployed by `../../helm/honcho/` as a ClusterIP service with no ingress. It runs two workloads from one upstream image: `honcho-api`, whose entrypoint provisions the database before serving, and `honcho-deriver`, which polls for enqueued work and does not provision. Because provisioning runs on every API start, the API stays at a single replica; a second would race the first.

Its state is a dedicated `postgres-honcho` release, which reuses the generic PostgreSQL chart with a `pgvector/pgvector` image because representations are stored as vectors, and the shared Redis release on database index 1, since Firecrawl already occupies index 0.

Every model-calling module — deriver, summary, embedding, all five dialectic reasoning levels, and both dream models — is pinned to LiteLLM through a mounted `config.toml`. Honcho's built-in defaults target each provider's own endpoint, so a module left unset would send this deployment's LiteLLM key to the wrong host. Model configuration lives in that file rather than in environment variables because the dialectic levels are a dict field that does not express reliably as environment settings; flat settings and secrets are still supplied as environment.

An Agent opts into memory by joining a memory **group**, whose id names one shared Honcho workspace (`af-pool-<group id>`) that every member reads and writes — so distinct Agents in a group see what the others have learned. Both runtimes are wired: OpenClaw swaps its single memory slot to the Honcho plugin, while Hermes reads a generated `honcho.json` from its state directory and runs Honcho alongside `MEMORY.md` and `USER.md` rather than replacing them. Deleting an Agent does not touch the shared pool — its past contributions stay for the other members; deleting the *group* is the one sanctioned path that erases the pool. Joining or leaving a group takes effect when the Agent is next started, because runtime configuration is built during start and never rewritten in place. Reaching Honcho is authenticated: each Agent carries a token scoped to its own pool workspace, minted at provisioning.

Honcho resolves model credentials per module rather than per workspace and sends no workspace identifier on model calls, so all Agents' memory work shares one LiteLLM key; memory spend is therefore apportioned across pools by each workspace's token share rather than read directly per Agent. See [`../adr/2026-09-21-shared-memory-pools-via-groups.md`](../adr/2026-09-21-shared-memory-pools-via-groups.md). Background dreaming is disabled by default because it performs model work on an idle timer, spending against that shared key with no user action.

## Observability

`../../helm/monitoring/` deploys namespace-scoped Prometheus, Grafana, and Alertmanager charts. The product API exposes platform probes on `:8000`, Ingest exposes telemetry metrics on `:8001`, and Communications exposes HTTP metrics on `:8002`; LiteLLM and Agent health services retain their existing scrape targets. Alert rules route through Alertmanager, and Grafana dashboards are provisioned from chart ConfigMaps.

## Restore point Jobs

Capture and restore run as `batch/v1` Jobs rather than pods managed by the API, and reuse the
API's own image so the archive logic and its exclusion sets are always the same build as the
API that scheduled them — `API_IMAGE` is rendered from the same chart expression as the API
container's `image`. Nothing new is built or published.

Both mount the Agent's `agent-<uuid>` PVC, which is why they require a stopped Agent. ReadWriteOnce is not the guarantee it looks like here: it is enforced per node for attachable volumes, and the default `local-path` provisioner is a bind mount with nothing to attach, so two pods on one node can hold the same directory. The API therefore waits for the Agent's pod to disappear before creating either Job, rather than trusting the Agent's stored status — stopping deletes the Deployment and returns immediately while the pod lives out its termination grace period. Capture
mounts the Agent volume read-only alongside a fresh per-restore-point PVC. Restore mounts
three — the Agent volume writable, the new Pre-Restore destination, and the chosen archive
read-only — and performs the safety-net capture and the extraction in one process, so the
backup is on disk before anything is wiped.

The wipe is not total. A short per-runtime list of paths survives it — Hermes' `config.yaml`,
OpenClaw's `openclaw.json` and `npm/` — because each runtime *merges into* its configuration
rather than rewriting it, and OpenClaw's plugin store holds install records and a host link into
the runtime image that only a network install recreates. Destroying them leaves the runtime
unable to boot with no way back: `gateway.mode` disappears from a regenerated `openclaw.json`,
and the plugin reinstall fails on the missing host peer link. That list is a strict subset of the
archive exclusions and is deliberately much smaller than it, because for the remaining excluded
paths the wipe is the only thing that prunes them — the aai-cli store and the skills directory
are both written additively at boot, so sparing them would leave a revoked credential or a
removed skill in place.

Capture and restore share one rule about what an archive may hold: every member is offered to the
same `tarfile.data_filter` the extraction applies, against a neutral destination, and anything it
refuses is dropped at capture with a count reported alongside the archive size. The neutral
destination matters — the filter is destination-sensitive, so a link resolving inside the volume's
live mount point still escapes the restore target, and filtering against the live path would let it
through. Hand-written rules about which links to keep drifted from what extraction actually
accepts, and each divergence failed a whole restore; deferring to the filter removes the class
rather than the case.

The wipe is total, and the archive is what puts state back. OpenClaw's npm plugin store is
captured rather than excluded, so the packages and the records of them in `state/openclaw.sqlite`
roll back together instead of disagreeing; the one thing an archive cannot carry is the store's
link into the runtime image, which the capture filter removes and `start.sh` recreates on the next
boot. Hermes' `.cache` is excluded as regenerable bulk. Sparing paths from the wipe was tried and
reverted: it left current packages beside capture-time records, and the wipe is the only thing
that prunes a revoked credential from the aai-cli store or a skill the Agent no longer has.

The Job runs as root. Extraction then applies the ownership the target volume already had,
read before the wipe, because the two runtimes differ: Hermes' init container chowns `/opt/data`
recursively, while OpenClaw's chowns only the mount point, so a restore cannot rely on the next
start to repair ownership. Ownership is re-applied with `lchown` and skips the preserved paths:
the preserved npm store links to a path inside the *agent* image, which the Job's own image does
not have, so following it would abort a restore whose target is already wiped.

The API learns each Job's outcome by reading its status, and its archive manifest by reading
the Job pod's logs — the manifest is written onto the restore point's PVC, which the API cannot
mount. Distinct exit codes separate a failed safety-net capture, where the Agent volume was
never touched, from a failed extraction, where it was.

A row's status is otherwise only resolved when someone reads it, so a CronJob runs the same
resolution on a schedule and reclaims what no row owns. It matches a Job or PVC back to its row
through the `agentbarn.io/restore-point-id` label, falling back to the resource's own generated
name — never through `job_name`, which is cleared when a row goes terminal. The name fallback is
what reaches resources created before that label existed; both routes are exact, because the
builders generate the names. Because that pass deletes storage from a list-and-compare, it skips
resources younger than a minimum age, caps deletions per run, refuses to delete a resource
identifiable by neither route, and fails no rows at all when the volume listing is empty or
failed.

CSI `VolumeSnapshot` is deliberately unused; see
[`../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md).

## Kubernetes client constraint

Kubernetes `stream()` and `portforward()` temporarily monkey-patch `ApiClient.request` while establishing WebSocket connections. They use a dedicated `CoreV1Api` and `ApiClient` so concurrent REST operations cannot hit the patched handler; keep streaming and ordinary CRUD clients isolated.

## Source map

| Concern                         | Source                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------- |
| Runtime orchestration           | `../../api/domains/agents/service.py`                                                 |
| Runtime configuration digest    | `../../api/domains/agents/runtime_digest.py`                                          |
| Ingest process and routing      | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh`                       |
| Communications process and routing | `../../api/communications_app.py`, `../../api/communications_main.py`, `../../api/domains/communications/` |
| Domain Event delivery workers   | `../../api/worker_app.py`, `../../api/domains/events/worker.py`, `../../api/domains/events/reconciliation.py`, `../../helm/agentbarn-api/templates/event-delivery-worker-deployment.yaml`, `../../helm/agentbarn-api/templates/event-delivery-reconciliation-cronjob.yaml` |
| Agent Restore Point reconciliation | `../../api/domains/restore_points/reconciliation.py`, `../../api/domains/restore_points/constants.py`, `../../helm/agentbarn-api/templates/restore-point-reconciliation-cronjob.yaml` |
| Shared Kubernetes builders      | `../../api/domains/agents/builders/common.py`                                         |
| Hermes builders                 | `../../api/domains/agents/builders/hermes.py`, `../../hermes-base/`                         |
| OpenClaw builders               | `../../api/domains/agents/builders/openclaw.py`, `../../openclaw-base/`                     |
| Private Agent trigger admission | `../../api/domains/agents/scripts/agent-trigger-server.py`, `../../api/domains/agent_webhooks/dispatch.py` |
| Skill and integration artifacts | `../../api/domains/agents/aai_cli_artifacts.py`, `../../api/domains/agents/aai_cli_skills/bundled/skills/`, `../../api/domains/agents/gog_artifacts.py` |
| Provider clients                | `../../api/infrastructure/slack/`, `../../api/infrastructure/telegram/`, `../../api/infrastructure/discord/` |
| Kubernetes client               | `../../api/infrastructure/kubernetes/`                                                |
| Charts and release ordering     | `../../helm/`, `../../helmfile.yaml.gotmpl`                                                 |
| Deployment workflow             | `../../.github/workflows/deploy.yml` (k3s), `../../.github/workflows/deploy-public.yml` (Talos public) |
| Monitoring stack                | `../../helm/monitoring/`                                                               |
| API metrics                     | `../../api/core/metrics.py`, `../../api/domains/communications/metrics.py`             |

## Change impact

Runtime changes must be checked against both runtime builders, images/base configuration, Agent lifecycle tests, telemetry, and the versioned Communications protocol. Platform changes belong at the Platform Plugin seam and require plugin, gateway, Connection CRUD/schema, and delivery tests rather than runtime branches. Chart template/value changes require the chart `version` bump according to `../../AGENTS.md`.
