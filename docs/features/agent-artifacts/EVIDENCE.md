# AF-415 verification evidence

Verified 2026-10-22 in the independent `feature/af-415-agent-artifacts` worktree,
starting at local AF-389 head `6e109add`. AF-389 PR
[#326](https://github.com/aai-labs/agent-barn/pull/326) remains open against staging.
The live AF-415 specification expanded on 2026-10-21 supersedes the older
workflow-owned storage design and historical POCs, which were left unchanged.

## Reproducible checks

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Affected API suite below | 201 passed, 52.36 seconds | Real migrated PostgreSQL, FastAPI routes and disposable Garage 2.4.1; no mocked S3 byte path |
| `HERMES_TEST_IMAGE=hermes-base:0.2.10 OPENCLAW_TEST_IMAGE=openclaw-base:0.7.7 make test-artifact-runtime` | 2 passed, 14.71 seconds | Generated CLI executes as each image's normal user, uploads/lists/links/retrieves real bytes through the API and Garage |
| `cd ui && pnpm exec playwright test tests/e2e/artifacts.spec.ts tests/e2e/workflow-runs.spec.ts` | 24 passed, 24.3 seconds | Chromium with intercepted API fixtures; fresh links, read-only Files access, denied download, run/step files alongside text and existing run behavior |
| `make check-api check-migrations` | Passed | Ruff lint/format, Python types, single Alembic head |
| `make check-ui lint-ui` | Passed | TypeScript and ESLint |
| `make check-artifacts check-workflows` | Passed | Helm 3.19.0 rendered contracts; private credentials reach only API/purge, shared retention, purge opt-in and no purge service-account token |
| `git diff --check` | Passed | Whitespace validation |

Affected API command (run from `api/`):

```sh
uv run pytest \
  tests/integration/test_artifacts.py \
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

## Limits and deployment acceptance

These are local integration and runtime-image contracts. The runtime tests use
an HTTP bridge into the real API; they do not ask an LLM to select the tool,
create a new Kubernetes Agent session, or send a file through an external chat
provider. Browser tests use synthetic metadata and download responses. No full
repository test-suite pass, external deployment, live messaging delivery or
production Garage validation is claimed.

AF-389's uncertain-effect automatic retry, session-stop/quiescence, live OpenClaw
Agent-session acceptance and run-read-policy coordination remain dependencies.
Artifact READY proves stored bytes, not external provider effects, safe replay
or tool quiescence. AF-390 remains the approval integration follow-up; file-backed
reviews must pin exact IDs/checksums and release their references explicitly.

Deployment still requires authorized private Garage provisioning, TLS endpoint
configuration reachable by download clients, a service-only bucket key in the
existing storage Secret, schema migration, and an opted-in purge schedule. Verify
fresh links and native messaging delivery in the deployed Hermes/OpenClaw sessions
before claiming that live acceptance. No merge or deployment was performed here.
