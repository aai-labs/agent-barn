# Garage storage operations

Read for persistent Agent artifact storage, bucket credentials, local bootstrap,
Kubernetes installation, TLS, backup, recovery or storage verification.
[Agent artifacts](../features/agent-artifacts.md) owns product access and lifecycle.

## Storage topology and identity

Garage 2.4.1 supplies the private S3 byte store; PostgreSQL supplies artifact metadata
and the durable deletion journal. Use a dedicated bucket per installation. The
application key receives bucket read/write only, with no owner or global bucket
creation permission. API and artifact purge receive that key. Agents receive only
their scoped Agent service credential. Garage RPC/bootstrap credentials stay in
Garage/operator configuration and never enter application or Agent Secrets.

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

First startup writes mode-0600 configuration/keys inside ignored mode-0700 `.garage/`.
Other state directories must be outside the repository. Secret key imports travel
through stdin rather than CLI arguments, keeping them out of exec request URLs,
audit metadata, process listings and Docker exec events.
The root `compose.yml` includes `docker/garage/compose.yml`: Garage is a required
service in the main application project, alongside the API and purge worker.
The helper prepares private configuration, starts that same service and provisions
a bucket-scoped application key. It also refreshes the non-secret saved path,
port and volume prefix (`GARAGE_SAVED_*`) in the existing ignored application
`.env`; keys remain only in private files. These generated values must not be edited.
The standalone helper still uses its private `compose.env`. The included file also lets storage-only recovery
commands run without application/provider configuration. Named metadata and data
volumes retain their exact names when adopting an older standalone local store;
the helper stops/removes only its old Garage container before starting the main
project's replacement. Keys, node identity, bytes and endpoint remain unchanged. The local S3
port is currently published on all host interfaces; authentication is still required.
Restrict host/network access for your development environment. Repeated startup
reuses identities, endpoint and volumes. Only S3 port 3900 is published; RPC/admin/
website endpoints are not published and website serving is disabled. Select another
port/origin on first setup when multiple worktrees run (the helper reads these two
settings from `.env` only during initial setup; explicit flags override shell values,
which override `.env`). Existing initialized stores reuse their saved configuration,
regardless of those defaults. Only explicit CLI changes are refused:

```sh
GARAGE_S3_PORT=13900 GARAGE_PUBLIC_ENDPOINT=http://192.0.2.10:13900 make garage-up
```

Use an actual host address, not that documentation address. By default the helper
uses the Linux Docker bridge gateway, reachable from the host browser, Compose and
k3d Agent pods. Docker Desktop, remote browsers or unusual bridge/firewall setups
must supply a host/origin reachable by all three. The S3 origin is also the signed
URL origin: never rewrite signed host/path. HTTP is for trusted local development;
cluster/browser sharing uses TLS. Add the origin to operator proxy bypass settings
if a host proxy otherwise intercepts local traffic.

Run `./run.sh` for normal startup. Garage and the ten-minute bounded purge worker
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
including when an initial pass precedes completion of API migrations. The API and purge alone read `.garage/application.env`.
The other shared application containers explicitly blank S3 credentials. The local
API container also hosts ingest and memory-runtime processes; those processes share
its environment and therefore its storage identity. Do not put
local Garage keys in shared `.env`. After `make garage-up` on an already running
stack, recreate API/purge so their environment is refreshed:

```sh
docker compose up -d --no-deps api
docker compose up -d artifact-purge
```

Native `make dev-api` and `make purge-artifacts` load the ignored application file
when present. The native API launch loads it only for the product API process.
Restart existing Agents to load file instructions/configuration. `make garage-down`
stops only Garage; `./stop.sh` stops the main stack. Both preserve named volumes and keys. Never use
`docker compose down --volumes`, Docker volume pruning, or delete `.garage/` against
retained developer data. The helper refuses to silently regenerate lost keys when
its named volumes still exist. Restore the private configuration from backup. Initialized stores also refuse missing
metadata/data volumes or a changed node ID; they never recreate an empty bucket
behind existing READY metadata. Restore a consistent backup into a fresh directory.
A failed, unpublished first startup removes only its own new volumes and remains
retryable with a different port/origin. A derived bridge endpoint follows the new
port on an unpublished retry; an operator-supplied origin is preserved. If cleanup itself fails, resolve the Docker
error before retrying; never remove volumes belonging to an initialized store.
A crash before `state.json` is written is refused as partial configuration. Preserve
that private directory and inspect its worktree-specific Compose volumes. If no
store was initialized and no volumes remain, move the partial directory outside
the repository and retry first setup. Otherwise recover from a consistent backup.

An empty/unconfigured artifact bucket retains text-only operation. Missing storage
is an artifact error, not an API readiness dependency. The domain limits remain
25 MiB per file by default, 900-second links with a default 3,600-second maximum,
and 30-day reference-relative retention. Configure application limits through
existing artifact configuration, not Garage bucket-wide age rules.

## Consistent local backup and restore

Backup/status queries explicitly select the Garage service, excluding other
containers in the main project. A backup refuses when Garage is not running and
does not start an intentionally stopped Garage because another service is up.
A local backup briefly stops Garage, copies metadata and data plus private bootstrap
configuration, marks completion, then restarts it if it was running. Backups include
credentials and must remain private. Destinations must be absolute, outside the
repository and outside the live configuration directory. Copy operations have no
fixed timeout so large backups are not truncated by a two-minute deadline. Back up PostgreSQL artifact metadata separately
at the same maintenance point; Garage bytes cannot reconstruct ownership/references.

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
storage nodes, suitable StorageClass/capacity, a TLS hostname reachable by API,
Agents and browsers, its DNS, and a valid TLS Secret. Installation is an explicit
operator action; these commands must not be run against production without authorization.

Generate private RPC and future application credentials locally (use a distinct
state directory for every installation). Nothing is printed or committed:

```sh
cd api
uv run python scripts/provision_garage.py cluster-config \
  --state-dir /absolute/private/garage-staging \
  --namespace agent-farm --endpoint https://files.example.com
```

Apply the generated RPC Secret only to that installation; then install storage
without waiting for S3 readiness, which requires the next bootstrap step:

```sh
kubectl --kubeconfig /authorized/staging.yaml apply --server-side \
  -f /absolute/private/garage-staging/rpc-secret.json
helm upgrade --install garage ./helm/garage --namespace agent-farm \
  --kubeconfig /authorized/staging.yaml --wait=false \
  --set storageClass=your-storage-class \
  --set ingress.enabled=true --set ingress.host=files.example.com \
  --set ingress.tlsSecret=garage-s3-tls
```

Run Helm from the repository root. The chart defaults to this project's Traefik
class, `websecure` TLS entrypoint and controller in `kube-system`. Override
`ingress.className`, `ingress.annotations`, `ingress.controllerNamespace` and
`ingress.controllerLabels` together for another controller. Set
`ingress.clusterIssuer` to request cert-manager issuance, or provide the TLS Secret
in advance. Helmfile/CI use the Traefik defaults and a pre-created TLS Secret.
A network plugin must enforce NetworkPolicy. DNS is allowed in `kube-system`;
NodeLocal DNS needs an installation-specific additional egress rule.
Only S3 is exposed. RPC is restricted to Garage peers; S3 accepts the application
and ingress controller. ServiceAccount tokens and privilege escalation are disabled.
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
for availability, creates the private bucket and grants a separate key read/write.
On repeat it preserves existing layout and identities, refusing unknown replacement
nodes rather than silently changing retained data placement. Node replacement,
capacity expansion and RPC/key rotation require explicit Garage repair/layout
procedures. Export and retain private bootstrap state in the installation's secret
backup system; never add it to the repository or CI logs.

After bootstrap, set deployment inputs in `.env.deploy`, or their CI Variables
(`STAGING_` prefix for staging, `PUBLIC_` for public, unprefixed for production):

```dotenv
GARAGE_ENABLED=true
GARAGE_S3_HOST=files.example.com
GARAGE_RPC_SECRET_NAME=garage-rpc
GARAGE_TLS_SECRET=garage-s3-tls
ARTIFACT_STORAGE_SECRET=garage-artifact-storage
ARTIFACT_PURGE_ENABLED=true
```

Helmfile then manages the Garage release and mounts the existing application Secret
only into API/purge. Initial install/layout bootstrap must finish before enabling
this path: existing deploy commands use `helmfile sync --wait`, so Garage readiness
also gates ordinary deployment. A missing replica/PVC can therefore delay or fail
a deploy; do not rely on the release's default `wait: false` to bypass CLI `--wait`
([pinned Helmfile flag logic](https://github.com/helmfile/helmfile/blob/v0.171.0/pkg/state/helmx.go#L109-L121)).
CI receives Secret names, not Garage key plaintext. Both storage
Secrets must already exist; no deploy hook regenerates or owns their credentials.
An externally managed Garage can leave `GARAGE_ENABLED=false` and use the same
application Secret contract. The Secret must contain `ARTIFACT_S3_BUCKET`,
`ARTIFACT_S3_ENDPOINT_URL`, `ARTIFACT_S3_REGION=garage`, `ARTIFACT_S3_ACCESS_KEY` and
`ARTIFACT_S3_SECRET_KEY`. Set application retention/limits in the API chart; workers
and purge must share retention settings. Restart API after rotating its key Secret.

For API chart configuration, set `artifacts.maxBytes`, `artifacts.linkMaxSeconds`,
`artifacts.retentionDays` and `artifacts.runtimeBaseUrl`; API and workflow workers
must agree on retention. Their environment equivalents are `ARTIFACT_MAX_BYTES`,
`ARTIFACT_LINK_MAX_SECONDS`, `ARTIFACT_RETENTION_DAYS` and
`ARTIFACT_RUNTIME_BASE_URL`. For native `make dev-api`, set the latter in `.env`
to the worktree API address reachable from Agent containers, for example
`http://host.docker.internal:8000/artifact-runtime/v1` with the actual API port.
Compose configures that host address from `API_PORT`.

AWS S3 remains an alternative: set the correct region, leave explicit access/secret
keys empty when using workload identity and grant object Put/Get/Delete only on
the installation's `artifacts/*` prefix. The application never creates buckets or
changes policies. Garage instead grants its dedicated key read/write to a dedicated
private bucket because its authorization model differs from AWS IAM.

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

Migration `a4150b8c9d10` follows `f8740a67b788`; migrate before new API/worker code.
Rollback admission/UI first and keep additive metadata plus purge tooling until
in-flight uploads settle/expire. Downgrade refuses any non-DELETED artifact, preserving
the only deletion journal. Before dropping tables, export required files or authorize
their deletion, release active references through their owning lifecycle, and finish
purge. An old API can run while the additive tables remain in place. Never change endpoint or bucket while retained rows still
target the old store; migrate and verify explicitly or preserve old access for purge.
Monitor Garage health/capacity and failed purge jobs, DELETING age and `purge_attempts`.
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
sign-in and Agent Files with unmocked artifact API/download requests after storage
restart. Cluster verification creates its own three-node k3d cluster and checks
quorum I/O during one-node outage plus persistent node identity/data recovery.
No test consumes installation credentials or current kubeconfig. See
[artifact evidence](../features/agent-artifacts/EVIDENCE.md) for exact outcomes and
limits: no external deployment, actual LLM selection, provider messaging or resolution
of inherited AF-389 retry/stop acceptance gaps is implied.
