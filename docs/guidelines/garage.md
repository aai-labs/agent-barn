# Garage storage operations

Read for persistent Agent artifact storage, bucket credentials, local bootstrap,
Kubernetes installation, TLS, backup, recovery or storage verification.
[Agent artifacts](../features/agent-artifacts.md) owns product access and lifecycle.

## Storage topology and identity

Garage 2.4.1 supplies the private S3 byte store; PostgreSQL supplies artifact metadata
and durable artifact/bucket deletion journals. Each Agent has a distinct private
bucket and read/write data key, with no owner or bucket-creation permission. The
API and file-purge worker resolve the target Agent's encrypted key from PostgreSQL;
there is no shared data credential or ambient workload-identity fallback. Agents
receive only their scoped Agent service credential.

The API holds Garage administrative authority and processes durable per-Agent storage
requests after the creation/Provision response. The existing artifact-purge worker uses the
same private authority for request recovery and deleted-owner reclamation. There
is no separate provisioner process or Agent-discovery scan. Management credentials
never reach Agent runtimes or other application workloads. Cluster NetworkPolicy
allows admin port 3903 only from API and artifact-purge pods. Local Compose also
publishes management on an automatically assigned **127.0.0.1-only** port for
native API/cleanup; it is never exposed to the LAN or an ingress. The API remains
trusted with the encrypted credential catalogue. Product ownership, readiness,
retry and deletion invariants are owned by the [artifact contract](../features/agent-artifacts.md#per-agent-storage-authority).

The local single-node service is for development. The cluster chart defaults to
three replicas, three-way replication, distinct Kubernetes nodes, separate metadata
and data PVCs, fsync and a disruption budget of two. The default volumes are 1 GiB
metadata and 10 GiB data per node. Assigned capacity is 10GB per node. Size capacity
below the actual data volume and maintain free headroom. Distinct Kubernetes nodes
must represent independent machines/failure domains; three local k3d nodes on one
host prove protocol behavior, not physical redundancy. Replication is not a backup.

Sources: [Garage cluster deployment](https://garagehq.deuxfleurs.fr/documentation/cookbook/real-world/),
[configuration](https://garagehq.deuxfleurs.fr/documentation/reference-manual/configuration/) and
[Kubernetes deployment](https://garagehq.deuxfleurs.fr/documentation/cookbook/kubernetes/).

## Persistent local setup

Install Docker Compose 2.24 or later with optional `env_file.required` support, and complete
`make setup` (uv/Python and application dependencies). Storage can start without
k3d, provider credentials or the rest of the application:

```sh
make garage-up
make garage-status
```

First startup writes mode-0600 configuration/keys inside mode-0700 `.garage/`,
excluded from both Git and Docker build contexts.
Other state directories must be outside the repository. Secret key imports travel
through stdin rather than CLI arguments, keeping them out of exec request URLs,
audit metadata, process listings and Docker exec events.
The root `compose.yml` includes `docker/garage/compose.yml`: Garage is a required
service in the main application project, alongside the API and purge worker.
The helper prepares private Garage configuration and the API/cleanup control-plane
credential. The API starts each requested bucket/key after the response. It also refreshes the non-secret saved path,
port and volume prefix (`GARAGE_SAVED_*`) in the existing ignored application
`.env`; keys remain only in private files. These generated values must not be edited.
The standalone helper still uses its private `compose.env`. The included file also lets storage-only recovery
commands run without application/provider configuration. Named metadata and data
volumes retain their exact names when adopting an older standalone local store;
the helper stops/removes only its old Garage container before starting the main
project's replacement. Keys, node identity and bytes remain unchanged. The local S3
port is published only on loopback for native development/operator access, never for
browser downloads. Compose API/purge use the private `garage:3900` service address.
Repeated startup reuses identities, endpoint and volumes. S3 and native-management ports are published only on loopback; RPC/website
endpoints are not published and website serving is disabled.
`GARAGE_S3_PORT` is optional: it defaults to 3900 and only selects the loopback
operator/native-development port. Set it (or pass `--port` to the helper) on first
setup if another local store already occupies that port; it is not a browser or
Agent setting. The helper reads initial port/endpoint defaults from `.env`, with
explicit flags overriding shell values and shell values overriding `.env`.
Existing initialized stores reuse their saved configuration; explicit CLI changes
require an intentional migration.

New stores default to `http://127.0.0.1:<port>` for native API/operator access;
Compose uses its internal service address instead. The legacy
`GARAGE_PUBLIC_ENDPOINT` bootstrap option names the **internal** S3 endpoint, not
a browser-facing address. Keep it private. Existing saved endpoints are not
silently changed. When upgrading a store using the old Docker-bridge host address,
change that saved non-secret endpoint to the loopback address for native use
(`endpoint` in `.garage/state.json` and `ARTIFACT_S3_ENDPOINT_URL` in
`.garage/application.env`); preserve the port, keys, node identity and volumes.
Do this while the API is stopped, then restart it. Compose's internal override
needs no saved-endpoint change. Old direct-to-storage URLs are superseded by fresh
app links. That endpoint-only operation does not migrate legacy shared-bucket
files into the new per-Agent layout. HTTP is for trusted local
storage traffic; externally shared app links use the existing app HTTPS origin.

Run `./run.sh` for normal startup. Garage and the bounded ten-second maintenance worker
are required, with no profile opt-in. The launcher prepares configuration and
bootstraps Garage before API/purge containers load their credentials; those services
also depend on Garage health in Compose. On first setup, use the launcher or
`make garage-up` after application `.env` setup and before invoking bare
`docker compose up`: starting Garage needs the generated private files. Root
Compose parsing, db/redis-only Make targets and `./stop.sh` work without `.garage/`.
Optional parse-time env files do not allow an unconfigured Garage to start: missing
config/secret bind sources fail without auto-creating them. Before bootstrap,
Compose uses a separate `.garage-unconfigured` path and
`<project>-garage-unconfigured_metadata` / `_data` sentinel volume names. A failed
bare Compose attempt can leave these empty sentinel volumes, but they never match
the real store's initialization guard. Normal `make garage-up` remains recoverable.
After successful bootstrap, operators may remove those two explicitly named sentinel
volumes if unused; never remove the configured store volumes. Subsequent `docker compose up` includes Garage and
purge automatically; `./stop.sh` stops them with the rest of the stack. Failed cleanup passes retry on the next interval,
including when an initial pass precedes completion of API migrations.
`.garage/application.env` contains only the private S3 endpoint; it has no
credentials or bucket naming configuration. API/purge read it. Both also read `.garage/provisioner.env` containing
`ARTIFACT_PROVISIONER_URL/TOKEN`. The retained file/setting names describe the
management client, not a separate running provisioner. Compose blanks management
authority in other workloads and shared data keys everywhere, even if an operator
put them in shared `.env`.
Never put Garage administrative credentials in shared `.env`. After bootstrap on
an already running stack, migrate and recreate these processes:

```sh
make migrate
docker compose up -d --no-deps api
docker compose up -d artifact-purge
# Upgrade only: stop/remove the retired worker if it exists.
docker compose rm -sf artifact-provisioner
```

Native `make dev-api` and `make purge-artifacts` load the ignored application file
and `.garage/provisioner-host.env`, generated by `make garage-up` from Docker's
actual loopback management binding. Rerun `make garage-up` after container
replacement, then restart the native API to refresh that address. The native
launcher loads this authority only into the product API, not its child gateways.
Set `GARAGE_ADMIN_PORT` in the shell if a fixed loopback port is needed; by default
Docker selects a free port, avoiding collisions across worktrees.
Restart existing Agents to load file instructions/configuration. `make garage-down`
stops only Garage; `./stop.sh` stops the main stack. Both preserve named volumes and keys. Never use
`docker compose down --volumes`, Docker volume pruning, or delete `.garage/` against
retained developer data. The helper refuses to silently regenerate lost keys when
its named volumes still exist. Restore the private configuration from backup. Initialized stores also refuse missing
metadata/data volumes or a changed node ID; they never recreate an empty bucket
behind existing READY metadata. Restore a consistent backup into a fresh directory.
A failed, unpublished first startup removes only its own new volumes and remains
retryable with a different port/origin. A derived loopback endpoint follows the new
port on an unpublished retry; an operator-supplied origin is preserved. If cleanup itself fails, resolve the Docker
error before retrying; never remove volumes belonging to an initialized store.
A crash before `state.json` is written is refused as partial configuration. Preserve
that private directory and inspect its worktree-specific Compose volumes. If no
store was initialized and no volumes remain, move the partial directory outside
the repository and retry first setup. Otherwise recover from a consistent backup.

An empty/unconfigured `ARTIFACT_S3_ENDPOINT_URL` retains text-only operation.
Bucket aliases are always `agent-artifacts-<agent UUID hex>`; no configurable or
saved installation prefix is needed because aliases are local to the scoped key.
Per-Agent data secrets
require the same `AGENT_TOKEN_ENCRYPTION_KEY` in API and purge.
Configured storage adds a PENDING provisioning request to the Agent creation
transaction; it never delays the creation response for Garage. Artifacts exposes
status and an explicit Provision/retry action for existing Agents. Post-response
API work attempts the request immediately; maintenance recovers interrupted tasks
and retries failures without changing the key identity. Local Compose runs bounded
maintenance every ten seconds. The enabled Kubernetes purge CronJob recovers
requests every ten minutes; Helmfile enables it by default when `ARTIFACT_STORAGE_SECRET`
is set. Supply both storage and management Secrets for unattended recovery; direct
chart installs must set `artifacts.purgeEnabled=true`. Requests remain durable if that
schedule is disabled, but require an explicit retry or `make purge-artifacts`.
Missing storage is an artifact error, not an API readiness dependency. The domain limits remain
25 MiB per file by default, 900-second links with a default 3,600-second maximum,
and 30-day reference-relative retention. Configure application limits through
existing artifact configuration, not Garage bucket-wide age rules.

## Download delivery

The existing `WEB_APP_URL` determines the download link origin; Garage remains
private. The provider generates, validates and expires the opaque signed authority
carried by the app URL. Runtime retrieval uses the Agent's reachable API origin.
Restart existing Agents after CLI updates. External recipients must be able to
reach the app's configured HTTPS origin; no public storage address is required.

The API uses bounded streaming, not a redirect or a full-file download buffer.
Account for download bandwidth/concurrency on API replicas, and set ingress and
app proxy read/idle timeouts for supported file sizes. Redact the `access` query
parameter (or omit query strings) in ingress, CDN and external access logs; do not
cache the download route. API access logging already redacts it. Provider failures
before streaming return 403/503 without private URLs or provider error bodies;
failures after headers can interrupt a download, so request a fresh link and retry.
No schema migration accompanies this routing change. Rollback preserves metadata
and bytes, but an older direct-S3 implementation requires private operator access
for downloads: do not re-expose Garage as a rollback shortcut.

## Consistent local backup and restore

Backup/status queries explicitly select the Garage service, excluding other
containers in the main project. A backup refuses when Garage is not running and
does not start an intentionally stopped Garage because another service is up.
A local backup briefly stops Garage, copies metadata and data plus private bootstrap
configuration, marks completion, then restarts it if it was running. Backups include
credentials and must remain private. Destinations must be absolute, outside the
repository and outside the live configuration directory. Copy operations have no
fixed timeout so large backups are not truncated by a two-minute deadline.
Stop API and artifact-purge writes for a consistent maintenance
point. Back up PostgreSQL metadata, including `artifact_bucket`, and preserve
`AGENT_TOKEN_ENCRYPTION_KEY` at that same point. Garage bytes cannot reconstruct
ownership/references or the encrypted per-Agent credential catalogue.

```sh
make garage-backup BACKUP_DIR=/absolute/private/backups/garage-2026-10-23
```

Test recovery with the original instance stopped. Restore requires a complete backup,
an empty target directory and fresh named volumes; existing volumes are never overwritten:

```sh
make garage-down
cd api
uv run python scripts/provision_garage.py restore \
  --state-dir /absolute/private/recovered-garage \
  --backup-dir /absolute/private/backups/garage-2026-10-23
uv run python scripts/provision_garage.py up --state-dir /absolute/private/recovered-garage
```

Use the recovered `application.env` for the API, or restore the configuration to its
normal `.garage` location only after retaining/moving the old configuration safely.
Preserve the origin when retaining existing signed links. If changing origin/port,
pass both `--port` and `--endpoint` on restore (a changed port alone is refused) and reconfigure API/clients explicitly;
old signed URLs cannot be rewritten. Do not run two copies of restored node identity.
A failed restore removes only the new target configuration and volumes it created;
fix the reported cause and repeat the same restore command. Existing stores are
never restore targets.

## Kubernetes installation and first bootstrap

The chart is namespace-scoped and creates no CRDs, cluster RBAC or ServiceAccount.
It uses stable per-replica RPC ClusterIP Services plus explicit operator peer/layout
bootstrap. Peers retain those Service addresses when a pod gets a new IP. This
requires the deployment identity to have namespace permissions for StatefulSets,
PVCs, Services, ConfigMaps, Secrets, NetworkPolicies, PodDisruptionBudgets and
Ingresses; namespace scope alone does not establish these grants. Prepare three schedulable
storage nodes and suitable StorageClass/capacity. Garage needs only private
service DNS reachable by API/purge; browsers and Agents download through the app. Installation is an explicit
operator action; these commands must not be run against production without authorization.

Generate private RPC/admin credentials and non-secret application storage settings locally (use a distinct
state directory for every installation). Nothing is printed or committed:

```sh
cd api
uv run python scripts/provision_garage.py cluster-config \
  --state-dir /absolute/private/garage-staging \
  --namespace agent-farm --endpoint http://garage.agent-farm.svc.cluster.local:3900
```

Apply the generated RPC Secret only to that installation; then install storage
without waiting for S3 readiness, which requires the next bootstrap step:

```sh
kubectl --kubeconfig /authorized/staging.yaml apply --server-side \
  -f /absolute/private/garage-staging/rpc-secret.json
helm upgrade --install garage ./helm/garage --namespace agent-farm \
  --kubeconfig /authorized/staging.yaml --wait=false \
  --set storageClass=your-storage-class \
  --set ingress.enabled=false
```

Run Helm from the repository root. Application Helmfile/CI leave Garage ingress
disabled; no storage hostname or public storage TLS Secret is required. The chart
retains an explicit optional ingress for independently managed operator installations,
not for the app download path. A network plugin must enforce NetworkPolicy.
DNS is allowed in `kube-system`;
NodeLocal DNS needs an installation-specific additional egress rule.
No Garage port is publicly exposed. RPC is restricted to Garage peers; S3 accepts
only API and artifact-purge pods when ingress is disabled. Admin port 3903 accepts
only API and artifact-purge pods; it has no ingress or cluster host-published port. ServiceAccount tokens and privilege escalation are disabled.
For a single-node development cluster, install Garage with `--set replicas=1
--set replicationFactor=1 --set requireDistinctNodes=false`, and bootstrap with
`cluster-init` after installation. For Helmfile set `GARAGE_REPLICAS=1`,
`GARAGE_REPLICATION_FACTOR=1`, and `GARAGE_REQUIRE_DISTINCT_NODES=false` in the
deployment environment. Always create the RPC Secret before syncing.
This development topology has no redundancy and must not be used as a production default.

A one-replica installation has no PodDisruptionBudget and provides no redundancy.
SQLite automatic metadata snapshots are not configured; consistent backups remain
required even with fsync and replication. PVCs survive pod/release replacement.
Recreating the RPC Services (for example,
a Helm uninstall/reinstall with retained PVCs) changes their ClusterIPs; rerun
`cluster-init` before resuming application traffic so peers reconnect to the new
addresses. Never uninstall storage with PVC deletion while
metadata references retained bytes. Verify StorageClass reclaim policy and physical
node/storage failure behavior independently of local tests.

Bootstrap explicitly with the target kubeconfig:

```sh
cd api
uv run python scripts/provision_garage.py cluster-init \
  --state-dir /absolute/private/garage-staging \
  --kubeconfig /authorized/staging.yaml --capacity 10GB
kubectl --kubeconfig /authorized/staging.yaml apply --server-side \
  -f /absolute/private/garage-staging/application-secret.json
kubectl --kubeconfig /authorized/staging.yaml apply --server-side \
  -f /absolute/private/garage-staging/provisioner-secret.json
```

`clusterDomain` defaults to `cluster.local`; override it for another cluster DNS
suffix. Bootstrap verifies that every advertised node address equals its replica's
RPC Service ClusterIP using the daemon's live `GetClusterStatus` data. `garage
node id` prints its configured hostname and does not establish the resolved
runtime address ([2.4.1 source](https://github.com/deuxfleurs-org/garage/blob/v2.4.1/src/garage/cli/local/init.rs)). If Garage has no resolved address (`null`) or an address different from its Service,
fix DNS/domain/network policy and restart that pod before retrying bootstrap.
Each Garage pod first runs a non-root, read-only BusyBox init container that waits
for its stable RPC Service DNS name over 120 lookup attempts with a one-second
pause between failures. DNS timeouts can make this longer than two minutes. It has no RPC/application
credentials or Kubernetes token. This keeps normal startup ahead of the daemon's
one-time address resolution; the live-address check remains the final fence.

The chart sets `rpcTimeoutMilliseconds=20000` and
`rpcPingTimeoutMilliseconds=3000`. Garage's upstream default RPC timeout is five
minutes, which can hold an outage read beyond the API adapter's 30-second S3 read
timeout. These in-cluster defaults bound peer attempts; tune them alongside client
timeouts for slower networks or heavy storage load, and repeat outage tests before
rollout. Helm validates both values as positive integer milliseconds before
creating resources. The RPC timeout bounds requests; the ping setting only tightens
the probe deadline, with failure detection still spanning several ping intervals.
They do not guarantee an outage-free request. See the pinned
[RPC timeout implementation](https://github.com/deuxfleurs-org/garage/blob/v2.4.1/src/rpc/rpc_helper.rs).

Bootstrap connects peers, assigns the initial layout only at version zero, waits
for availability, and writes separate application-settings and provisioner Secrets.
Per-Agent bucket/key creation runs after explicit API creation/Provision responses;
the existing maintenance worker recovers pending requests.
On repeat it preserves existing layout and identities, refusing unknown replacement
nodes rather than silently changing retained data placement. Node replacement,
capacity expansion and RPC/key rotation require explicit Garage repair/layout
procedures. Export and retain private bootstrap state in the installation's secret
backup system; never add it to the repository or CI logs.

After bootstrap, set deployment inputs in `.env.deploy`, or their CI Variables
(`STAGING_` prefix for staging, `PUBLIC_` for public, unprefixed for production):

```dotenv
ARTIFACT_STORAGE_SECRET=garage-artifact-storage
ARTIFACT_PURGE_ENABLED=true
ARTIFACT_PROVISIONER_SECRET=garage-artifact-provisioner
```

Helmfile always manages the Garage release; there is no enable/disable deployment
flag. Its configured application storage settings reach API/purge;
the dedicated provisioning Secret reaches only those two workloads.
Initial install/layout bootstrap must finish before application deployment:
existing deploy commands use `helmfile sync --wait`, so Garage readiness
also gates ordinary deployment. A missing replica/PVC can therefore delay or fail
a deploy; do not rely on the release's default `wait: false` to bypass CLI `--wait`
([pinned Helmfile flag logic](https://github.com/helmfile/helmfile/blob/v0.171.0/pkg/state/helmx.go#L109-L121)).
CI receives Secret names, not Garage credential plaintext. RPC/admin, application
settings and provisioner Secrets must already exist; no deploy hook regenerates
them. The application Secret contains only `ARTIFACT_S3_ENDPOINT_URL`, with no
data credentials or bucket naming options. Signing always uses `garage`;
there is no region environment variable or provisioner Deployment. `garage-rpc` is the standard RPC/admin Secret name;
application Helmfile/CI need no name-override variable.
The dedicated provisioner Secret contains `ARTIFACT_PROVISIONER_URL` (private
`http://garage:3903`) and `ARTIFACT_PROVISIONER_TOKEN`. Garage loads `GARAGE_ADMIN_TOKEN` from the `admin-token` key
in its RPC/admin Secret; never mount that Secret in API or Agent workloads.
Set retention/limits in the API chart; workers and purge share retention settings.

For API chart configuration, set `artifacts.maxBytes`, `artifacts.linkMaxSeconds`,
`artifacts.retentionDays` and `artifacts.runtimeBaseUrl`; API and workflow workers
must agree on retention. Their environment equivalents are `ARTIFACT_MAX_BYTES`,
`ARTIFACT_LINK_MAX_SECONDS`, `ARTIFACT_RETENTION_DAYS` and
`ARTIFACT_RUNTIME_BASE_URL`. For native `make dev-api`, set the latter in `.env`
to the worktree API address reachable from Agent containers, for example
`http://host.docker.internal:8000/api/v1/agent-artifacts/runtime` with the actual API port.
Compose configures that host address from `API_PORT`.

The byte-store adapter and automatic provisioning target Garage; signing uses
the fixed `garage` region. Another provider needs an adapter/provisioner with the
same per-Agent bucket/key invariants. Do not substitute installation-wide credentials or workload identity.
The API provisions/verifies requested private Agent buckets asynchronously; the
cleanup worker recovers requests and reclaims deleted-owner storage.

The adapter uses SigV4 path-style Put/Get/Delete with optional SDK checksum trailers
disabled in favor of explicit SHA-256 readback. Garage 2.4.1 ignores conditional Put;
the locked application lifecycle supplies immutability. Exclude other bucket writers.
Never configure bucket age expiry to remove pinned objects. The app creates no public
bucket grants, website configuration or storage-wide credentials.

## Cluster backup, repair and application rollback

Back up Garage metadata/data and PostgreSQL together. Use storage snapshots or an
independent backup system with a tested Garage recovery procedure; three replicas
on one shared disk/provider are not three independent copies. Retain private layout,
RPC and application key configuration. Follow [Garage durability/repair](https://garagehq.deuxfleurs.fr/documentation/operations/durability-repairs/)
and [recovery](https://garagehq.deuxfleurs.fr/documentation/operations/recovering/)
for the deployed version. A lost node's data is repaired from remaining copies;
replacement node IDs require explicit layout changes, not the initial bootstrap tool.

Artifact migration `a4150b8c9d10` follows `f8740a67b788`; merge revision
`a4151c9d0e21` joins the prerequisite history. New head `a4152d0e1f32` adds the
per-Agent bucket/key journal. No-op merge `fac0030afc38` joins that history with
staging's Agent Sizes head `8b2e4f61c9d3`; it performs no schema/data operations.
Run `make migrate` before the updated processes.
This change assumes no existing files: there is **no shared-bucket byte migration
or legacy shared-key access**. Old local buckets/volumes are not automatically
deleted. Do not apply it to an installation retaining shared-bucket files without
a separately approved migration plan.
Rollback admission/UI first and keep additive metadata plus purge tooling until
in-flight uploads settle/expire. Downgrade refuses any non-DELETED artifact, preserving
the only deletion journal. Before dropping tables, export required files or authorize
their deletion, release active references through their owning lifecycle, and finish
purge. The bucket-journal downgrade additionally refuses every non-DELETED bucket:
finish artifact purge, bucket reclamation and key revocation before discarding it.
Retain additive tables and compatible API/purge processes during rollback. Never change endpoint or bucket while retained rows still
target the old store; migrate and verify explicitly or preserve old access for purge.
Monitor Garage health/capacity and failed purge jobs, DELETING age and `purge_attempts`. Alert on failed or overdue artifact-purge Jobs and Pending Jobs; check pod scheduling events and available memory (the Job requests the worker resources). A stuck Job stops retention and provisioning recovery.
Unsafe-target refusals retain evidence and retry backoff; investigate rather than
discarding the journal. Operator recovery uses bounded `make purge-artifacts` passes.

## Verification

```sh
make check-artifacts
cd api && uv run pytest tests/integration/test_garage_persistent.py -q
# From the root, with already-built runtime images and Chromium installed:
HERMES_TEST_IMAGE=hermes-base:0.2.10 OPENCLAW_TEST_IMAGE=openclaw-base:0.7.7 make test-artifact-deployment
make test-garage-cluster
```

The first integration contract uses the shipped Compose/bootstrap path, verifies
private grants, signed bytes after container replacement, backup/fresh-volume restore
and API purge. The deployment contract includes both runtime CLI images, real local
sign-in and Agent Artifacts with unmocked artifact API/download requests after storage
restart. Cluster verification creates its own three-node k3d cluster and checks
quorum I/O during one-node outage plus persistent node identity/data recovery.
No test consumes installation credentials or current kubeconfig. See
[artifact evidence](../features/agent-artifacts/EVIDENCE.md) for exact outcomes and
limits: no external deployment, actual LLM selection, provider messaging or resolution
of inherited AF-389 retry/stop acceptance gaps is implied.
