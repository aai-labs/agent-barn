# AF-415 verification evidence

Initial implementation verified 2026-10-22; independent-review corrections verified locally 2026-10-23 in the independent `feature/af-415-agent-artifacts` worktree,
starting at local AF-389 head `6e109add`. AF-389 PR
[#326](https://github.com/aai-labs/agent-barn/pull/326) remains open against staging.
The live AF-415 specification expanded on 2026-10-21 supersedes the older
workflow-owned storage design and historical POCs, which were left unchanged.

## Post-rebase verification — 2026-10-26 (local, not pushed)

The working revision was committed before rebasing onto freshly fetched
`origin/staging` at `e207a212` (including AF-389 merge `42ea3fc7` and Agent Sizes).
Conflict resolution retained staging's init-container resources, Agent-size API
inventory and cleanup setup alongside artifact behavior. The earlier artifact
merge migration was retained and no-op `fac0030afc38` joins both current heads.

- **255** affected artifact/configuration/persistence/builder/inventory/Agent-size
  tests passed in **169.37 seconds**.
- **16** additional Agent-size migration/container-resource tests passed in
  **10.46 seconds**.
- Both real-image CLI tests passed in **13.16 seconds**; the authenticated
  Chromium/runtime/persistent-Garage contract passed in **25.18 seconds**.
- API lint/format/types, UI types/lint, single migration head and artifact/workflow
  chart checks pass. Local migrations are applied, paused services restarted,
  and app health is 200. Cluster verification was not repeated for the rebase.

These are local commits, not a remote push/PR retarget or external deployment.
Earlier independent review still does not cover the current storage architecture.

## Fixed Agent-derived names — 2026-10-26 (local, not pushed)

The maintainer removed the unnecessary installation-prefix configuration. Bucket
names are now always `agent-artifacts-<agent UUID hex>`; bootstrap generates no
prefix and application settings contain only the existing private endpoint.
An empty endpoint retains text-only operation without a replacement toggle.

- **167 focused API/configuration/persistence/builder/inventory tests passed** in
  143.16 seconds. Retired prefix-validation cases were replaced by fixed-name and
  removed-configuration regressions; cross-Agent provider-ID/key denial remains.
- Both runtime CLI contracts passed (**2 tests, 13.35 seconds**) and the
  authenticated browser/runtime/persistent-storage contract passed (**1 test,
  25.21 seconds**). API lint/format/types, migration-head, chart and whitespace
  checks pass. The prior three-node pass below predates this naming-only revision;
  cluster topology and token delivery are unchanged.
- The single local development bucket was verified empty with no retained artifact
  metadata targeting it before its key-local alias was normalized. Its provider ID,
  credentials and bytes were preserved; no legacy file migration or deletion was
  performed. The unused saved prefix was removed, settings/processes refreshed,
  and app health returns 200.

This revision remains local/unpushed and is not covered by the earlier independent
approval. No production provisioning or deployment occurred.

## Per-Agent buckets and isolated provisioner — 2026-10-26 (local, not pushed)

The maintainer approved a separate privileged provisioning process and explicitly
excluded migration of existing files. This revision supersedes the shared-bucket
configuration in older evidence. The feature contract and Garage operations guide
own the current topology, credential boundaries and fresh-layout requirement.

- Real Garage tests prove distinct provider bucket IDs and data keys for Agents
  in the same and different Organizations. Each key is denied cross-Agent reads
  and overwrites using **both private aliases and actual provider bucket IDs**;
  anonymous reads, bucket creation and owner operations are denied too.
- Durable retry tests cover loss of a successful bucket-creation response and
  loss of a successful key-revocation response without replacing identities.
  Soft/hard owner deletion keeps credentials until artifact bytes are purged,
  then reclaims the bucket, revokes the key and clears the encrypted secret.
  Initializing storage returns 503 without staging file metadata. Migration tests
  prove journal-preserving downgrade refusal and permitted cleanup/upgrade.
- A test-process-only mutation deliberately assigned two Agent-local aliases and
  keys to one actual Garage bucket. The isolation regression failed at the
  distinct-provider-ID assertion. The unmutated test passes. Provider identity is
  also unique in the database schema. No unsafe mutation touched live source.
- Both real-image CLI contracts passed (**2 tests, 13.37 seconds**) with Hermes
  `0.2.10` and OpenClaw `0.7.7`. The real runtime/persistent-Garage/authenticated
  Chromium contract passed (**1 test, 25.88 seconds**). An initial browser-harness
  attempt failed because the extracted host pnpm script lacked execute permission;
  fixing that tooling permission produced the passing rerun.
- Helm 3.19.0 was extracted from the cached image after the download hostname was
  unreachable. Rendered contracts verify the provisioning Secret reaches only
  its dedicated Deployment and admin port 3903 admits only provisioner pods.
- Local `make garage-up` preserved old buckets, node identity and named volumes.
  `make migrate` applied the additive journal, and API/provisioner/purge/worker
  configuration was refreshed. One local Agent bucket is READY and app health
  returns 200. API environment checks confirm no shared S3 key/secret or
  provisioning URL/token. Old shared-bucket files were not migrated or deleted.

Final combined verification passed **176 API/configuration/persistence/builder/
inventory tests in 143.34 seconds**, plus `make check-api`, `make check-migrations`,
`make check-artifacts` and diff whitespace checks. After the deployment review,
provisioning is unconditional, signing is fixed to `garage`, and the optional RPC
Secret-name deployment variable is removed; the actual `garage-rpc` Secret remains
required. The real Garage fixture verifies Secret-backed admin-token environment
injection.

The disposable three-node quorum/PVC-recovery contract passed (**1 test,
254.69 seconds**) after correcting Kubernetes admin-token delivery. Two initial
attempts failed at startup because Garage requires exactly `0600` for token files,
rejecting both normal projected permissions and `0440`. Kubernetes now injects
`GARAGE_ADMIN_TOKEN` from its Secret like the existing RPC secret; the strict file
check is not relaxed. These tests prove startup/quorum/recovery, while admin-port
source restriction and workload Secret isolation are rendered-chart contracts.
No production access, external rollout, push or merge occurred. Earlier independent
approval predates these changes; a new independent review is still required.
Live LLM file-tool selection, external messaging and inherited AF-389 acceptance
remain outside the passing offline/runtime/browser contracts.

## Private storage and app byte downloads — 2026-10-26 (local, not pushed)

The maintainer requested that Garage remain private and that bytes pass through
the app, while **provider signing, signature validation and expiry remain with
S3**, not an application token issuer. This supersedes the earlier direct-storage
URL/public-storage-ingress evidence below. The abandoned separate public-storage
endpoint workaround was removed before this delivery.

- A real-Garage regression first failed because the returned origin was storage,
  not the configured app origin. It now passes with exact downloaded bytes through
  the capability-only app route. No private origin, bucket or object key is returned.
- **54 focused API tests passed** across artifact publication/review/download,
  streaming/log redaction, Compose isolation and the v1 operation inventory.
  **7 persistent-Garage tests passed** separately, covering retained authority
  across replacement/backup/restore, purge and main-stack adoption. The first
  combined run exposed old direct-S3 test requests and inherited developer saved
  Compose settings; those harness assumptions were corrected and rerun green.
- **2 real-image CLI tests passed** using Hermes `0.2.10` and OpenClaw `0.7.7`,
  including retrieval through the runtime's reachable app origin.
- **1 real runtime/API/persistent Garage/authenticated Chromium contract passed**
  in 55.14 seconds: two runtime uploads, Garage replacement, login, three exact-byte
  downloads whose URL origin/path are the app, and purge. The first attempt lacked
  host pnpm; the rerun used the existing host pnpm executable. No live LLM/tool
  selection or external messaging-provider delivery is claimed.
- `make check-api` passed (Ruff lint/format and Python types). `make check-artifacts`
  passed with checksum-verified Helm 3.19.0, including no default Garage ingress
  and S3 ingress policy restricted to API/purge pods.
- A test-process-only security mutation replaced supplied download authority with
  newly service-issued authority. The real-provider target-substitution regression
  failed at expected 403 versus actual 200; restoring the genuine implementation
  passed. No insecure mutation was applied to the running app.
- On the running developer stack, the previously reported 161-byte CSV downloaded
  through **`localhost:3000` with HTTP 200**. Missing/tampered authority returned
  403; app health returned 200. Garage now publishes only `127.0.0.1:13915` for
  operator/native use, while API/purge use `garage:3900`. Stored keys/volumes/bytes
  were retained; the saved native endpoint was updated from bridge to loopback.

Maintainer review corrections were reverified locally on October 26: the app byte
route is now `/api/v1/agent-artifacts/...`, the provider-neutral contract is named
`ArtifactStorage`, Garage is an unconditional Helmfile release, and setup-specific
SSH guidance has been removed. The renamed route passes **54 focused API tests**,
**2 real-image CLI tests** (14.52 seconds), and **1 real authenticated-browser
runtime/storage contract** (50.99 seconds). API lint/format/types, artifact chart
renders and diff whitespace checks also passed; the running app health returned 200.
`GARAGE_S3_PORT` remains an optional local loopback operator/native override only.

No schema migration, production access, external deployment, merge or push was
performed for this correction. Earlier independent approvals and full-suite
results apply to their named revisions, not to this unpushed change. Existing
Agents need a normal update/restart to receive the revised retrieval CLI.

## Natural file-delivery instructions — 2026-10-26 (local, not pushed)

The shared runtime instructions now map ordinary requests for a file/export to
creating and publishing the finished deliverable and returning its actual download
link. Users need not name storage or the CLI. Exceptions cover keep-local requests,
text/code replies, scratch/intermediate files and unrelated workspace contents;
normal tool approvals and messaging policy remain in effect.

Both generated-runtime configuration tests first failed on missing outcome-driven
instructions, then passed after the prompt update. **92 Hermes/OpenClaw builder
and runtime-digest tests passed** in 8.59 seconds; `make check-api` and diff whitespace
checks passed. These prove instruction assembly and update detection contracts,
not LLM compliance. Existing Agents need an update/restart and a fresh conversation
with an ordinary request such as “Create a CSV with three sample products.” No new
live model/tool-selection or external messaging acceptance is claimed.

## Independent review and follow-ups — 2026-10-26 (local, not pushed)

GPT 6.1 Sol reviewed the complete uncommitted diff with medium reasoning/full
access using the code-review-and-quality skill and returned **APPROVE, no Critical
or Required findings**. The review includes the final domain-owned
`mount_agent_artifacts` routing helper. Independent checks passed: 54 focused
artifact/configuration/inventory tests, 99 persistence/builder/digest tests, both
real-image CLI cases, the authenticated Chromium/private-storage download case,
API lint/format/types and storage chart rendering. Two isolated security/response
mutations were caught; no unsafe mutation touched the running app.

Both optional notes were addressed afterward: the stale SSH-guidance claim was
removed from the delivery log, and a retained ASGI HTTP 2.3 test now disconnects
after a streamed chunk and verifies upstream cleanup without invoking its close
callback directly. The resulting focused suite passed **55 tests** in 30.92 seconds;
API lint/format/types and diff whitespace checks passed. Those small follow-ups
were locally verified, not independently re-reviewed. Live model/tool selection,
external message delivery and inherited AF-389 acceptance gaps remain unverified.

## Composed router and runtime URL revision — 2026-10-26 (local, not pushed)

The maintainer authorized moving the machine protocol under the product app so
app composition can include a real domain APIRouter once, rather than a mounting
helper. Management/download URLs remain unchanged; runtime uses
`/api/v1/agent-artifacts/runtime` and the previous root path returns 404. Runtime
credentials remain independent of user sessions, and the child remains outside
the public user schema. Defaults, Compose/Helm configuration and all test callers
were updated. Existing Agents and explicit runtime URL overrides need updating.

- **147 focused artifact/configuration/inventory/builder/digest tests passed** in
  35.22 seconds; both runtime cases assert that the removed root URL returns 404.
- **2 signing-region configuration tests passed** in 3.23 seconds: Garage defaults
  to `garage`, with an explicit region override retained for another provider.
- Both real-image CLI cases passed in **14.83 seconds** and the authenticated
  Chromium/runtime/persistent-storage case passed in **49.87 seconds** using the
  new machine URL. API lint/format/types, storage chart rendering and whitespace
  checks passed.

This wire/configuration revision follows the earlier independent approval and is
not represented as independently re-reviewed. At that point bucket-per-Agent
storage and its separate provisioning boundary were still pending; the later
per-Agent revision documented above supersedes that shared-bucket configuration. No production access, push, merge or external deployment occurred.

## Pre-base-update verification and push authorization — 2026-10-24

The maintainer explicitly authorized pushing after verification on October 24.
Earlier October 23 notes about local-only work and awaiting push agreement are
historical. The implementation uses the documented whole-Agent runtime trust
boundary; it does not claim isolation between sessions belonging to one Agent.

- Full standard API suite: **5,659 passed in 966.19 seconds**, with four isolated
  pytest workers; the separately selected Kubernetes file is excluded by this target.
- Full non-cluster runtime-image suite: **28 passed in 135.66 seconds** with
  Hermes `0.2.10`, OpenClaw `0.7.7` and the real pinned host CLI binary.
- Real runtime/API/persistent Garage/authenticated-browser deployment contract:
  **1 passed in 64.46 seconds**. Both CLI uploads and a Files download survive
  Garage replacement; providers/model tool selection remain outside this boundary.
- Fresh three-node Garage quorum/PVC/changed-pod-IP recovery: **1 passed in
  151.40 seconds**. This adds one local sample; it is not a general HA guarantee.
- API lint/format/types, UI lint/types, single migration head, memory/workflow/
  artifact chart checks and monitoring checks passed. Local API container and
  optimized UI production builds passed; no image was published or deployed.
- Full CI-style browser suite: **934 passed, 5 skipped in 9.4 minutes**. The five
  pre-existing Gmail OAuth cases remain explicitly skipped, not claimed as tested.
- Clean disposable Kubernetes API suite: **19 passed in 95.73 seconds**.
- Both runtime images passed their CI smoke/native/startup/resource-metric checks.
- Lockfile timestamp-only metadata was removed to match the base format; parsed
  dependency resolution, versions, sources and hashes were proven identical, and
  `uv lock --check` passed. The branch adds only the four required S3 SDK packages.

These results cover AF-415 source at `5479f75e` before integrating the advanced
prerequisite branch. GitHub reported conflicts because that branch now includes
newer staging/billing work and removal of the old workflow active-run cap. The
combined source requires a fresh verification pass, recorded separately below.

Initial setup failures were corrected before accepting results: the Docker-only
Helm wrapper could not read temporary values files, so checks used native pinned
Helm 3.19.0; monitoring required its pinned dependencies; two host CLI contracts
initially lacked their binary and passed with it configured. The first browser
run lost its development server during parallel builds, causing connection
failures; it was interrupted and restarted using the documented CI production
server/two-worker configuration. The first disposable Kubernetes run passed
18 cases and returned no logs in one multiline-log case; the clean rerun is
passed with all 19 cases. No source behavior was weakened to suppress those failures.

## Current prerequisite integration — 2026-10-24

Integrated prerequisite head `37901c38` rather than publishing a conflicting draft.
The shared cleanup fixture retains artifact and billing tables, and the epic log
retains both histories. No-op head `a4151c9d0e21` joins artifact migration
`a4150b8c9d10` with prerequisite head `b9e32d74a610`; publication and guarded
rollback invariants remain unchanged. Incoming removal of the workflow active-run
cap is preserved and does not weaken per-artifact attempt/generation fences.

The focused artifact/migration/workflow compatibility suite passed **58 tests in
34.45 seconds**, including guarded downgrade and re-upgrade through the combined
migration graph. All API/UI lint/types/format, migration, chart and monitoring
checks passed on the combined source. All non-cluster runtime contracts plus the
real artifact deployment boundary passed **29 tests in 177.12 seconds**. The API
container rebuild passed, and both runtime health-script contracts passed against
the incoming source. The Kubernetes client/test and Garage chart/cluster probe are
unchanged by this integration, so their earlier 19-case and quorum/recovery results
remain applicable. The full combined API suite passed **5,841 tests in 671.55
seconds**. The full CI-style browser rerun passed **984 cases with 5 existing Gmail
OAuth skips in 10.4 minutes**. The final API container build also passes with private
`.garage/` excluded from its build context. No existing locked package version
changed relative to the updated base; the only added packages are boto3, botocore,
jmespath and s3transfer. A new Opus review attempt was rate-limited; the prior independent approval
covers its reviewed artifact revision, not an unperformed integration review.

## Reproducible checks

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Affected API suite below | 218 passed, 57.42 seconds | Real migrated PostgreSQL, FastAPI routes and disposable Garage 2.4.1; no mocked S3 byte path |
| `HERMES_TEST_IMAGE=hermes-base:0.2.10 OPENCLAW_TEST_IMAGE=openclaw-base:0.7.7 make test-artifact-runtime` | 2 passed, 13.89 seconds | Generated CLI executes as each image's normal user, uploads/lists/links/retrieves real bytes through the API and Garage |
| `cd ui && pnpm exec playwright test tests/e2e/artifacts.spec.ts tests/e2e/workflow-runs.spec.ts` | 25 passed, 27.3 seconds | Chromium with intercepted API fixtures; fresh links, read-only Files access, denied download, run/step files alongside text and existing run behavior |
| `make check-api check-migrations` | Passed | Ruff lint/format, Python types, single Alembic head |
| `make check-ui lint-ui` | Passed | TypeScript and ESLint |
| `make check-artifacts check-workflows` | Passed | Helm 3.19.0 rendered contracts; private credentials reach only API/purge, shared retention, purge opt-in and no purge service-account token |
| `git diff --check` | Passed | Whitespace validation |

Affected API command (run from `api/`):

```sh
uv run pytest \
  tests/integration/test_artifacts.py \
  tests/integration/test_artifact_review.py \
  tests/integration/test_artifact_migration.py \
  tests/integration/test_workflows.py \
  tests/integration/test_workflow_runs.py \
  tests/unit/test_agent_trigger_server.py \
  tests/unit/test_hermes_builders.py \
  tests/unit/test_openclaw_builders.py \
  tests/unit/test_public_api_contract.py -q --tb=short
```

Helm ran through the local `alpine/helm:3.19.0` image with the worktree mounted
read-only. Storage tests create their own temporary Garage configuration,
fixture-only keys, private bucket and PostgreSQL instance; they remove disposable
containers on exit. No production bucket or credentials are involved.

Real-image identities used for the CLI tests:

- Hermes `hermes-base:0.2.10`: `sha256:8b922f14ba5ff8773fa20178f256c2872249a359e3242bb562bbe84b9ebe7a80`.
- OpenClaw `openclaw-base:0.7.7`: `sha256:8a27c59b29bbf7c97a24e8ce8ad87370f5caca84baf19d938cb5000bd3402fc4`.
- Garage `dxflrs/garage:v2.4.1`: `sha256:9c96caa2612d3411acc5b0e6701fb238dbfba33e533a6d7d3d811a4b12d0d020`.

[UI screenshots](evidence/README.md) show the Files, run and selected-step views
with synthetic browser fixtures.

## Behaviors exercised

The API tests cover actual private byte retrieval and anonymous denial, SHA-256
and size validation before READY, duplicate/concurrent finalization without byte
replacement, new identity on replacement, 15-minute links with bounded lifetimes,
actual expired-link rejection, and fresh authorized links. Garage returns HTTP
400 for an expired signature; the contract requires rejection, not a particular
S3 error status.

Authorization coverage includes agent.read-only users and API keys without
activity permission, scoped visibility loss, cross-Organization/Agent IDs,
agent.update publication/deletion, runtime credential rotation, stale workflow
attempts, attempt expiry during storage and human membership loss during storage.
Workflow tests cover exact artifact IDs/checksums in later-session checkpoint
handoff, active run pins, review pins, final reference release and retention.
Cleanup coverage includes incomplete/failed uploads, a storage failure after
bytes were accepted, retryable purge failures, canonical tenant-safe key refusal,
owner hard deletion with surviving cleanup metadata, and guarded migration
rollback. Unconfigured storage preserves successful text-only workflow execution.

## Independent Opus 5.5 review follow-up (2026-10-23)

The independent review requested changes. These corrections are local and unpushed;
PR #328 still contains the earlier revision. The user requires explicit agreement
before any further push. The review found a completion-token disclosure in the
file-publication prompt, run locks held over S3, unsafe-target retry starvation,
insufficient mutation coverage, unbounded workflow file manifests and missing RBAC
exception documentation. These findings supersede the initial self-review's claims.

- **C1:** Only the attempt ID enters file-tool arguments. The existing Agent
  credential authorizes artifact publication through a public owning-Agent fence;
  it cannot complete/fail an attempt. The completion bearer never enters the prompt
  or CLI arguments. A human cannot publish to a workflow-staged artifact.
- **R1:** S3 holds only the artifact lock. It is released before the final run then
  artifact lock sequence. The regression probes both locks during real S3 I/O,
  cancels the run during upload and observes fenced publication.
- **R2:** Unsafe bucket/key refusals commit attempt count and retry backoff. A
  one-candidate purge regression proves a refused target does not starve a newer
  expired upload.
- **R3:** Dedicated regressions cover file-lock exclusion, no READY rewrite,
  credential rotation during storage and expired staging inside finalization.
  Each fails under its corresponding mutation. Reintroducing the completion token
  also fails the prompt/authority regression. All five mutations were restored.
  Identical-byte concurrency alone was insufficient evidence for these invariants.
- **R4:** Admission under the run lock caps staged/READY files at 16 per attempt
  and file-reference JSON at 16,000 UTF-8 bytes across the run. The overall context
  error names both summaries and references. Both admission limits are tested.
- **R5:** The RBAC brief now explicitly records artifact runtime identity and the
  two operator-only unscoped purge methods.
- **O1–O7:** Pin release and orphan-run repair preserve pending deletion retries;
  routes check metadata/deadline and cap request buffering to declared size;
  workflow file rows display attempt identity; settled/parked runs stop file
  polling; workflow fencing uses a public method; the S3 client is reused; and
  unconfigured storage omits model file-tool instructions. Regressions cover retry
  timing, instruction gating, attempt display, settled polling and protocol rejection.
- **Nits:** Clarified current run pins versus future checkpoint/review pins and
  canonical workspace path handling; CLI errors include safe HTTP status codes;
  filenames reject control/format characters, including DEL/bidi; link schemas
  require HTTP(S); imports and scope control flow were simplified; changelog
  spacing corrected. Generated lockfile timestamp churn is explained below.

### Second review and overlapping-upload correction

Opus's second review passed 33 focused artifact tests and found one remaining
Required item: a second writer could acquire the file lock after the first write,
while the first finalizer held the run lock waiting for that writer's S3 call.
Both publication phases now acquire the artifact lock with NOWAIT. Lock contention
returns retryable 409 and bypasses failed-upload marking, preserving another
writer's file and permitting a later retry of the same ID. Regressions hold a real
S3 writer open and independently contend finalization, checking that the run lock
is free, the file remains UPLOADING on conflict, and a retry reaches READY. Both regressions
fail when NOWAIT is changed back to a blocking lock. Those two additional mutations
were restored before the final 218-test affected API pass.

The owning Agent remains the runtime trust boundary, now explicit in the artifact
contract and RBAC brief: any session of that Agent can publish to its live attempts.
The attempt ID is non-secret provenance. This is an explicit local proposal for
maintainer agreement before any push; it does not claim per-session isolation or
change the approved existing-Agent execution model. A publication-only bearer
visible to the model/transcript would not by itself isolate sessions sharing the
same runtime, tools and Agent credentials.

Additional second-review fixes derive error limits from constants, move fresh
runtime/membership revalidation between the byte phase and final run-lock phase,
lock artifact rows before orphan-release expiry updates, reject human workflow
PUTs before consuming request bytes, and correct the runtime assembly instructions'
storage-start configuration/restart contract. No second-review finding has been
silently treated as deployment acceptance.

### Final independent verdict

Opus 5.5 approved the local working tree with no Required findings. It reran all
15 review regressions against real PostgreSQL/Garage with caches and bytecode
disabled: 15 passed in 9.99 seconds. It verified both publication contention paths
roll back and release their locks without failed-upload marking, and reviewed the
phase-gap deletion, expiry, attempt and authority fences. It did not rerun the
parent's mutation, 218-test API, runtime-image or browser suites.

The review clarified that preservation applies specifically to lock contention.
An admitted duplicate with mismatched bytes or a storage failure can still mark
shared staging DELETING. The CLI starts a new artifact on a new upload invocation;
it does not automatically retry the same ID. Abandoned staging counts against its
attempt's file limit until cleanup. These are consistent with the current documented
whole-Agent boundary and failed-upload lifecycle.

Code review approval is not maintainer agreement to push or acceptance of the
proposed trust boundary. All corrections are committed locally without a push; PR #328
is unchanged. No merge or deployment is authorized or performed.

The initial review additionally reported 2,740 unit and 371 related integration
passes from a disposable archive of the earlier revision. Those results are the
reviewer's evidence and do not count as reruns of these local corrections. It did
not rerun browser, Helm or runtime-image suites.

## Review and capability findings

The code-review-and-quality skill was applied across correctness, readability,
architecture, security and performance. Review fixes include post-storage human
membership revalidation, preserving staged uploads after invalid attempt tokens,
restricting orphan repair to run references, and making interrupted DELETING rows
immediately eligible for cleanup. API lists are scoped before filtering/counting
and bounded by pagination; upload buffering is capped by the configured byte
limit; purge processes at most 100 candidates per invocation.

A disposable Garage capability probe showed that 2.4.1 ignores `If-None-Match` on
PutObject. The adapter makes no conditional-write or WORM claim. Immutability is
provided by locked publication, fixed size/checksum metadata, unique artifact
keys and skipping writes for READY objects. Concurrent publication and changed
bytes are tested against Garage. Operators must keep the bucket private and
exclude other writers, as described in the storage setup.

The review mutation experiment inverted the publication checksum comparison.
`test_real_private_bytes_signed_download_and_fresh_link` failed at publication
(expected 200, received 422). Restoring the comparison made the focused suite
pass, followed by the complete affected suite above. No mutation remains.

The new SDK dependency is boto3 with botocore, jmespath and s3transfer; existing
locked package versions were preserved. The regenerated lock also records upload
timestamps from the current uv resolver. The SDK's optional request/response
checksums are configured `when_required` for Garage compatibility; explicit
application SHA-256 readback remains mandatory.

## Persistent infrastructure follow-up (2026-10-23, local and unpushed)

The original disposable boundary left no repeatable normal Garage installation.
This follow-up adds the shipped persistent Compose service/private bootstrap,
API/native launch wiring, local scheduled purge, consistent backup and non-overwriting
restore, plus the namespace-scoped three-node chart and explicit operator bootstrap.
[Garage operations](../../guidelines/garage.md) owns repeatable setup and recovery.

- `tests/integration/test_garage_persistent.py` plus
  `tests/unit/test_garage_configuration.py`: **8 passed in 62.90 seconds** (three
  persistent-storage cases and five configuration tests). Uses the shipped
  Compose/bootstrap configuration, bucket read/write-only key, real product API,
  private signed bytes, container/network replacement, stopped consistent backup,
  restore into fresh volumes with preserved keys and existing links, deletion,
  purge and abandoned-upload cleanup. Additional regressions cover occupied-port
  first-start retry, partial-restore cleanup/retry, refusal to replace lost volumes,
  outside-repository backup paths, `.env` validation and conflicting defaults on
  restored startup. Real Docker exec events contain the stdin key-import command
  and exclude the application secret.
- `make test-artifact-deployment`: **1 passed in 49.80 seconds**. Both actual runtime
  images run the mounted CLI and publish through the API into persistent Garage.
  After container replacement, Chromium performs real sign-in, opens Agent Files,
  sees both filenames and downloads/checks exact bytes three times. No route or
  download interception. The API uses disposable migrated PostgreSQL and fixture
  identities/MockK8s/MockLiteLLM adapters; no actual LLM turn or provider send.
- `make test-garage-cluster`: the final DNS-gated, bounded-RPC configuration
  passed **2 of 2 fresh-cluster samples**, in **165.26 seconds** and **141.91 seconds**,
  including stdin-based key import through real `kubectl exec -i`. The rendered chart is applied once and bootstrap
  repeated without layout/key changes. All three non-root pods run on distinct
  Kubernetes nodes with separate PVCs and private RPC credentials. With one node
  cordoned and its Garage pod absent, two ready S3 Service endpoints remain and
  actual S3 reads/writes succeed. Replacement recovers the same node ID and exact
  bytes, with a required change of pod IP and live daemon address matching the
  stable RPC Service IP. The test removes only its own cluster. All nodes share one Docker host;
  physical HA is unproven. Port forwarding to a surviving pod exercises bytes;
  endpoint assertions check Service availability, not external ingress/TLS.
- Earlier fresh-cluster probes exposed an insufficient initial pod/PVC startup
  allowance and failure to reconnect after a pod IP changed. Bootstrap now allows
  three minutes per pod; stable per-replica RPC ClusterIP Services preserve peer
  addresses across replacement. The complete fresh-cluster test above passes with
  those fixes. Earlier manual-cluster evidence alone did not establish this.
- An isolated copied-script mutation removed the pre-start lost-volume guard.
  Its real Docker regression failed at the intended assertion: empty replacement
  volumes were created. The worktree was never mutated; the probe cleaned up its
  own containers/volumes.
- `make check-artifacts check-workflows`: passed, including Traefik TLS/controller
  NetworkPolicy shape, stable RPC Services, null annotations with cert-manager,
  and omission of a one-replica disruption budget. API lint/format/types passed.
  The complete affected API set passed **237 tests in 121.39 seconds**: artifacts,
  publication review regressions/migration, workflow definitions/runs, runtime
  trigger/builders, persistent storage and configuration isolation. This is an
  affected-area pass, not the entire repository suite. The final live-address
  parser correction and null-address refusal are separately covered by the eight
  final focused storage/configuration cases and the real cluster samples above.

Independent infrastructure review found seven Required items: ingress compatibility,
first-start/restore failure recovery, lost-volume refusal, safe operator errors,
standalone `.env` handling, credential-bearing backup destinations and missing
operational guidance. All were corrected; the second review confirmed those fixes.
That review additionally found secret exposure through key-import argv and defaults
incorrectly overriding saved stores. Imports now use JSON on stdin, including
`kubectl exec -i`; stored Compose settings also resist inherited shell overrides.
The third review confirmed both fixes and identified a stale derived endpoint
when retrying a failed first start on a new port. State now records whether its
origin was derived; an unpublished retry rebuilds that origin for the new port,
while operator-supplied origins remain intact. The regression covers both paths,
with developer configuration isolated. A copied-script mutation that retained
the original endpoint failed at the intended endpoint-port assertion and cleaned
up only its own volumes.

Bootstrap additionally verifies every advertised node address against the stable
RPC Service ClusterIP using live `GetClusterStatus` data; the cluster DNS suffix is
configurable. A stricter check initially compared `node id` text and failed the
test: upstream 2.4.1 source confirms that command prints the configured hostname,
not the daemon's resolved address. Both bootstrap and recovery now inspect the
actual daemon response instead. That corrected bootstrap passed, but its outage
read exceeded the bounded client timeout (the run failed in 255.43 seconds).
Garage's pinned source defaults RPC attempts to five minutes; this establishes a
deadline mismatch, but no RPC trace was captured to prove the particular failed
request waited on that timeout. The chart now explicitly configures 20-second RPC and
3-second ping timeouts; the real outage check is repeated without increasing the
client timeout. One cached-image sample then passed; a second refused an invalid
live address at startup before creating application credentials. The chart now
waits for the RPC Service DNS name in a non-root init container and retains the
live-address fence; the final repeated samples are recorded above. The test also
verifies platform-scoped containerd image imports because k3d had returned success
after missing-digest failures, leaving registry-dependent pod pulls. Recovery asserts
that the replacement pod IP differs while its node ID and Service address remain
unchanged. Recreating Services requires repeated bootstrap, as documented.
Secret application uses server-side apply, and restore refuses a changed port
without a supplied endpoint.

Old state without an explicit unpublished marker is treated conservatively as an
initialized store. Private state paths are restricted to ignored `.garage` or
outside the repository. Opus 5.5's fourth infrastructure review approved the fixes
with no Required findings. Its fifth, focused review approved the corrected live
RPC address measurement against pinned upstream source and passed the five config
unit tests. That review did not run the parent cluster or affected API matrix.
The sixth review approved the RPC timeout defaults against pinned upstream source;
the seventh approved the DNS init container, platform-specific cache helper and
schema validation. Its required staging note was addressed by including the Helm
schema. All final local samples and earlier failed probes are distinguished here;
two passing samples do not prove general failover reliability, production HA or
an outage-free request guarantee. The infrastructure remains local with no push.

No external deployment or production resources were accessed.

## Required Garage in the main Compose stack — 2026-10-23

This follow-up supersedes the earlier opt-in local profile. Root Compose includes
the Garage service definition in the main project; Garage and artifact-purge have
no profile. Normal startup bootstraps private configuration before API startup;
API/purge also declare a healthy-storage dependency. Storage-only commands retain
the same service definition for recovery without launching unrelated application
services. Earlier default standalone stores are adopted with their exact volume
names, node identity, endpoint and credentials retained.

- Existing persistent storage/recovery plus configuration checks: **8 passed in
  62.80 seconds**. These include real Garage/PostgreSQL/API publication, replacement,
  backup/restore, purge and failed-first-start cases, plus configuration unit checks.
- New main-stack adoption check: **1 passed in 38.06 seconds**. A disposable old
  store receives actual S3 bytes, is adopted, and is started through root Compose.
  Root Compose reuses the adopted container and the bytes remain downloadable.
  Application/provider services are not launched by this case; default model
  rendering proves Garage/purge inclusion and health dependencies separately.
- A mutation that disabled main-project adoption failed at the intended project
  assertion: the helper stayed in its old standalone project. The script was
  automatically restored after the experiment; only disposable test storage was used.
- Final combined storage/configuration suite after compatibility adjustments:
  **9 passed in 96.43 seconds**, including the legacy private-config status check.
- Python lint/types, shell syntax, diff whitespace and artifact/workflow chart checks passed.
- A fresh Opus 5.5 review attempt could not run because the Claude API rate limit
  was reached. Earlier approvals apply to their reviewed revisions; they do not
  certify this follow-up. Local code review and verification cover this delta.

The existing worktree developer store was also backed up and adopted locally.
Its container is healthy under the main project, retaining the prior named volumes,
endpoint, application keys and public node identity. Its data files match the
consistent pre-adoption backup by SHA-256. The first post-move check assumed the
older state contained `node_id`; it did not, so identity was verified against the
backed-up public node-key file instead. Root Compose cannot start the complete
application in this checkout because required application `.env` values are absent
(including `POSTGRES_USER` and `API_PORT`). No application credentials were invented;
the complete root-Compose storage path was verified by the disposable adoption test
with explicit fixture settings, separately from this retained local store.

### Opus main-stack review corrections

Opus round 9 found two Required regressions: mandatory private interpolation files
blocked pre-bootstrap root Compose commands, and unscoped `compose ps` treated
other main-project containers as Garage during backup/status. Both were reproduced
before fixes: config failed with no `.garage`, and a real disposable project with
another running service entered backup instead of returning the expected refusal.

Root Compose now parses without private Garage files. Optional env-file defaults
retain `create_host_path: false` on required config/secret binds, so an unconfigured
Garage cannot start. Default-store bootstrap mirrors only non-secret saved path,
port and volume names into an existing application `.env`; credentials remain in
private files. Launch/stop discard inherited saved values after refresh. Backup
and status select only Garage. README/native setup and operations guidance move
with the changes; the adoption fixture also uses a unique project name.

The focused combined suite passed **11 tests in 108.49 seconds**, including real
Garage/PostgreSQL storage/recovery and the new no-private-config/other-service
regressions. The expanded other-service regression then passed **2 cases in
25.78 seconds**, covering missing and stopped Garage containers. In an isolated
copy, making `server.env` mandatory again failed the pre-bootstrap config test at
its intended assertion; the real tree was untouched. `make check-api`, shell syntax and whitespace checks
passed. Round 10 confirmed both fixes and found that fallback volume creation
could still poison first-time setup. Unconfigured defaults now use distinct sentinel
paths/volume names, and a real Docker regression attempts the failed bare start
before proving normal first bootstrap succeeds (**1 passed in 11.58 seconds**).
An isolated mutation restoring the unsafe real-name defaults failed at the intended
real-volume-allocation assertion; the worktree was untouched. This preserves the guard against
reinitializing retained real storage. Empty sentinel volumes are documented and
cleaned explicitly by that test. The symlink advisory was also addressed by resolving
the application `.env` before updating its public settings. The complete final
focused suite passed **13 tests in 125.56 seconds**, including no-private-config,
missing/stopped-container inventory, actual pre-bootstrap failure/recovery, storage
publication/restart, backup/restore, purge and adoption. Opus round 11 independently
approved the final correction with no Required findings and confirmed R1/R2 remain
resolved. Its six unit/configuration cases, pre-bootstrap regression and two
backup/status cases passed **9 tests in 33.63 seconds**; API quality, shell syntax
and whitespace checks also passed. It did not rerun the complete storage suite or
launch/stop the full application end to end. The 13-case result above is the parent
verification, distinct from that independent subset.

No push, merge, production access or external deployment was performed.

## Limits and deployment acceptance

These are local integration and runtime-image contracts. The runtime tests use
an HTTP bridge into the real API; they do not ask an LLM to select the tool,
create a new Kubernetes Agent session, or send a file through an external chat
provider. The original 25-browser-test suite uses synthetic metadata/download
responses; the additional persistent deployment check above uses real authenticated
API/storage downloads. No full
repository test-suite pass, external deployment, live messaging delivery or
production Garage validation is claimed.

AF-389's uncertain-effect automatic retry, session-stop/quiescence, live OpenClaw
Agent-session acceptance and run-read-policy coordination remain dependencies.
Artifact READY proves stored bytes, not external provider effects, safe replay
or tool quiescence. AF-390 remains the approval integration follow-up; file-backed
reviews must pin exact IDs/checksums and release their references explicitly.

External deployment still requires authorized execution of the provided Garage installation/bootstrap,
private S3 service connectivity, the existing public app HTTPS origin reachable by
download clients, the generated service-only bucket key in the existing storage
Secret, the artifact schema migration, and an opted-in purge schedule. No public
Garage endpoint is required. Existing deployments that enabled the former storage
ingress must remove it and use the internal service endpoint in their storage Secret. Verify
fresh links and native messaging delivery in the deployed Hermes/OpenClaw sessions
before claiming that live acceptance. No merge or deployment was performed here.
