# Testing guidelines

## Core principles

- Changed behavior needs coverage at the lowest layer that proves the contract reliably.
- Assert meaningful outputs and durable state, not implementation details or a mock's internal state.
- Test happy paths, authorization/permission failures, important validation failures, and not-found/conflict behavior.
- Regression fixes SHOULD include a test that fails for the original defect.
- Keep setup reusable, interactions centralized, and assertions close to the behavior being specified.
- Run repository `make` targets when available.

## Behavior-first regression tests

A regression test must reproduce the reported failure before it is used to
justify a fix. Establish the observable contract, run the test against the
unfixed code, and record the failure at the intended assertion. Source
inspection can suggest a cause, but is not reproduction evidence.

- Test at the real boundary where the defect occurs. A unit assertion on a
  generated configuration proves only the generator; behavior that depends on
  a runtime image, database, subprocess, protocol, or browser needs a contract
  test at that boundary.
- Make preconditions explicit before asserting the failed behavior. For
  example, prove that startup succeeded and a Skill file was materialized
  before asserting that the runtime lists and loads it. This distinguishes a
  discovery defect from provisioning, mounting, or permissions failures.
- Do not count a harness failure as reproduction. Fix import paths, fixture
  permissions, cleanup, dependency setup, and process invocation until the
  test fails specifically on the reported behavior.
- Run the same test red and green: it must fail on the original behavior and
  pass after the fix without weakening or replacing its assertions.

Prefer assertions on responses, persisted rows, emitted events, posted
payloads, rendered UI, files visible to a consumer, or results returned by the
real dependency. Mocks and fakes MAY isolate unrelated boundaries or make
failure modes deterministic, but an assertion against calls recorded by a mock
is insufficient when the contract concerns what another component actually
accepts or produces. Do not test a fake's behavior and infer that the real
runtime behaves the same way.

## GivenPy scenarios

Python tests use the lightweight GivenPy-style helpers in
`../../api/tests/core/givenpy.py` with pytest and PyHamcrest. GivenPy structures
a test; it does not replace the test runner or assertions.

- `given([...])` composes setup steps that state domain facts. Steps SHOULD be
  higher-order functions such as `skill_is_present(content)` so they can accept
  inputs and be reused. Store produced objects on `context`; keep JSON
  serialization, Docker commands, HTTP construction, and similar mechanics in
  dedicated helpers.
- A setup step MAY return a context manager such as `LambdaWith` when it owns
  cleanup. GivenPy exits returned context managers in reverse setup order.
- `when(...)` names one meaningful action and SHOULD contain one short call.
  Hide command construction, probe installation, execution, and output parsing
  behind an action helper such as `start_hermes_agent(context)`.
- `then(...)` asserts observable outcomes with PyHamcrest. Use separate,
  readable `then` blocks for closely ordered evidence such as “the file was
  materialized,” “the Skill was listed,” and “the Skill was loaded.”

```python
with given(
    [
        image_is_built(image),
        skill_is_present(skill_content),
        hermes_runtime_is_configured(),
    ]
) as context:
    with when("the Hermes agent starts"):
        result = start_hermes_agent(context)

    with then("Agent Barn should materialize the assigned Skill"):
        assert_that(result.workspace_file_exists, is_(True))

    with then("Hermes should list and load the assigned Skill"):
        assert_that(result.listed_skills, has_item(skill_name))
        assert_that(result.skill_loaded, is_(True), result.skill_error)
```

## Verification commands

Complete the [README development setup](../../README.md#development), then
invoke verification from the repository root. API tests force Organization and
Agent budget defaults to $100 and $25 respectively, so developer `.env`
deployment limits cannot change their expected budget contracts.

| Command | Coverage | Additional prerequisites |
| --- | --- | --- |
| `make check-api` | Ruff lint/format check and Python type checking | None |
| `make fix-api` | Ruff autofix and formatting; modifies files | None |
| `make check-migrations` | Exactly one Alembic head | None |
| `make check-memory` | Rendered gateway/backend isolation and authentication contracts | Helm 3.19.0 |
| `make test-api` | API unit and integration tests, excluding the Kubernetes client test | Docker for Testcontainers PostgreSQL and the pinned Prometheus image, plus Node.js for the OpenClaw plugin and healthz metrics tests |
| `make test-api-k8s` | Kubernetes client integration test | Docker plus a configured, disposable Kubernetes cluster whose target namespace already exists |
| `make test-integration-isolation RUNTIME=both` | Opt-in Secrets/PVC transition contracts in a new disposable k3d cluster | Docker, k3d, kubectl, locally built `HERMES_TEST_IMAGE` and `OPENCLAW_TEST_IMAGE`; no provider accounts |
| `make test-api-runtime` | Runtime contract tests against an explicitly selected built image | Docker and the image variable required by the selected test, such as `HERMES_TEST_IMAGE` |
| `make coverage` | All API tests with terminal and XML coverage, including the Kubernetes client test | Docker, Node.js, and the Kubernetes prerequisites above |
| `make lint-ui` | ESLint | None |
| `make check-ui` | TypeScript type check | None |
| `make test-ui` | Playwright end-to-end suite | Installed Chromium browser |
| `make check-monitoring` | Prometheus rule tests and dashboard PromQL parsing | uv, Helm, Docker, and built chart dependencies |

Install the Playwright browser once after dependency setup:

```bash
(cd ui && pnpm exec playwright install chromium)
```

On Linux, use
`(cd ui && pnpm exec playwright install --with-deps chromium)` when the host
also needs Playwright's system packages.

Before `make check-monitoring`, prepare the pinned chart dependencies:

```bash
helm dependency build helm/monitoring
```

The Kubernetes test creates and deletes resources in `K8S_NAMESPACE`, which
defaults to `agent-farm`. Confirm `kubectl config current-context` and use a
disposable local cluster and namespace; never point this test at production.

From `../../ui/` when debugging Playwright:

```bash
pnpm test:watch
pnpm test:debug
```

Choose commands for the touched area. Full Kubernetes or browser suites are required when the changed contract depends on those environments, not for unrelated documentation-only changes.

## API tests

API behavior changes MUST cover:

- Happy path.
- Authentication and relevant role/tenant failures.
- Key validation failures.
- Not-found and conflict behavior.
- Migration behavior when the database schema changes.

Integration tests use the real FastAPI app, migrated PostgreSQL, and additive Injector overrides. Follow the [GivenPy scenario conventions](#givenpy-scenarios) used in `../../api/tests/integration/`:

- Use PyHamcrest `assert_that` and matchers instead of bare `assert` statements.
- Each test SHOULD prove one behavior. Split independent assertion clusters into focused tests; grouping closely related fields into one matcher is appropriate when they describe one outcome.

Keep domain setup helpers under the existing test support structure rather than embedding large setup blocks in each test. Unit tests under `../../api/tests/unit/` are appropriate for services, repositories, parsers, builders, and infrastructure adapters when HTTP composition is not the contract under test.

Representative sources:

- Tenant isolation: `../../api/tests/integration/test_cross_org_isolation.py`
- Agent lifecycle: `../../api/tests/integration/test_agents.py`
- Templates and skills: `../../api/tests/integration/test_templates.py`, `../../api/tests/integration/test_skills.py`
- Ingest/activity: `../../api/tests/integration/test_ingest.py`, `../../api/tests/integration/test_conversations.py`, `../../api/tests/integration/test_tool_calls.py`
- Test application setup: `../../api/tests/conftest.py`, `../../api/tests/core/`

## On-demand integration isolation verification

Run the same deployment-boundary suite locally or manually in GitHub Actions.
It is outside `api/tests/` and normal PR workflows, so `make test-api` does not
collect it. The **Integration Isolation (on demand)** workflow
(`../../.github/workflows/integration-isolation.yml`) accepts Hermes, OpenClaw,
or both and builds the selected images from the chosen Git ref before testing.
It publishes a JUnit report and never pushes images or deploys to an existing cluster.

For local runs, reuse images built from the code under test:

```bash
docker build -t hermes-base:isolation hermes-base
docker build -t openclaw-base:isolation openclaw-base
HERMES_TEST_IMAGE=hermes-base:isolation \
OPENCLAW_TEST_IMAGE=openclaw-base:isolation \
make test-integration-isolation RUNTIME=both
```

Use `RUNTIME=hermes` or `RUNTIME=openclaw` and only its image variable to test
one runtime. `RUNTIME` defaults to Hermes, consistently with the other runtime
target. Install k3d (the CI/local bootstrap CLI pin is v5.8.3) and kubectl first;
Docker must support privileged k3d node containers. The suite pins
`rancher/k3s:v1.31.5-k3s1`, imports local images, creates its own uniquely named
cluster and kubeconfig, and deletes that cluster on completion or test failure.
It never uses the current Kubernetes context, application `.env` credentials,
or an existing Agent PVC. A force-killed runner may leave an `isolation-*`
cluster; inspect `k3d cluster list` and delete that specific test cluster.

The contract runs generated setup and pinned CLI binaries as the images' own
non-root users, with separate Jobs and Kubernetes Secrets for each phase and a
shared PVC. It seeds direct credentials, rotates the PVC SharePoint grant,
rejects a handoff and verifies preservation, applies isolation, repeats boot,
and hands the newest service grant back to direct mode. It reads the actual
isolated Secret and ConfigMap to check for embedded renewable credentials, verifies known CLI store
entries are gone, exercises GitHub proxy and SharePoint token-url authentication,
and checks that a missing dedicated token cannot use an unrelated environment token.
A NetworkPolicy permits only cluster DNS and the in-cluster fixture
boundary; each phase waits for policy enforcement, proves a second listening
fixture port is unreachable, and confirms the allowed port is reachable before
setup. Successful phases emit phase/uid metadata. Failure diagnostics may
include fixture values; the suite uses no real credentials.
The old Job pod and Secret are removed before the next phase starts. JUnit
results are written to the ignored `.scratch/isolation-junit.xml`.

This is a **runtime deployment contract**, not a complete application E2E test:
it uses a fake provider/broker boundary and does not deploy the product API,
real credential gateway, UI, LLM, or live provider accounts. API tests own actual
gateway authorization/revocation, database rotation/cache, RBAC, tenancy,
preflight and lifecycle error handling. Existing offline image contracts own
typed Graph files/Excel and gog import. Keep those checks alongside this suite;
a green cluster run alone does not prove their contracts.

## Runtime plugin tests

Direct Google credential import is tested against the real pinned gog binary in
both selected runtime images, with networking disabled. The contracts are
`../../api/runtime_tests/test_hermes_gog_direct.py` and
`../../api/runtime_tests/test_openclaw_gog_direct.py`; they run through
`make test-api-runtime` with the corresponding image variable. They prove the
generated client/token setup imports a grant that gog can decrypt from its
file keyring, without contacting a live Google account.

SharePoint contracts run the pinned patched aai-cli in both real images with external networking disabled. A loopback stub verifies POST token requests, dedicated-token failure without environment fallback, typed files/Excel auth, sign-in-marker continuity, failed handoff preservation, mixed provider cleanup and latest-grant handback. The API matrix covers both directions for every provider/runtime, legacy migration, source ownership, failure/retry/restore permissions, durable broker rotation/cache and reconnect. These tests use fixture grants only. Run `make test-api-runtime RUNTIME=hermes` with `HERMES_TEST_IMAGE`, or the OpenClaw equivalent with `OPENCLAW_TEST_IMAGE`. The image must be rebuilt after the pinned CLI/patch changes; an old local tag cannot prove this contract.

Agent Memory gateway tests replay sanitized Hermes and OpenClaw request captures
from `../../api/tests/fixtures/agent_memory/` through a real HTTP listener. They
cover the outbound bank, forced tags, document/operation namespaces, lifecycle
credential rotation, and response redaction. The wire models target Hindsight
0.10.2. Changes to this contract should also validate rewritten payloads against
that pinned image's `RecallRequest`, `RetainRequest`, and `ReflectRequest` models.

The API suite also runs the Hindsight cost bridge contract inside the pinned
`ghcr.io/vectorize-io/hindsight:0.10.2` image, pulling it if absent. A deterministic
HTTP model listener verifies concurrent bank identity and background consolidation;
no real model key is used. Memory cost integration tests cover exact persistence,
replay/healing, Organization totals, renewal-window isolation, and migration rollback.
Deletion cleanup tests cover atomic tombstone/grant changes, rollback/replay, backend
recovery, expired leases and stale completions, unsafe targets, and late retained
documents. The pinned-image purge test verifies private/shared removal without
changing another Agent or bank. Test queue migrations against already deleted Agents.
Explicit Organization Memory write tests cover read-only and combined read/write grants, immediate revocation, cross-Agent write rejection, runtime credential use, content-only payloads, and refusal handling. The shared writer targets Python 3.12 in Ruff, matching the oldest runtime. Both pinned-runtime startup contracts execute the mounted writer command; Hermes
executes the command from its generated instructions through the real terminal
tool, covering short-name discovery after shell PATH changes and explicit 403
refusals. Runtime fixtures mount the same executable ConfigMap command into the
standard binary directory. Gateway spend tests exercise real HTTP requests with persisted runtime snapshots,
memory charges, and successful-sync heartbeats. Cover exhausted/zero/uncapped
limits, precise combined totals, missing/stale data, renewal, immediate limit
changes, and recall availability when changing this policy. Failed and truncated
spend-log runs must leave the heartbeat unchanged.

The pinned viewer tests also cover exact private scopes, grant/revoke visibility
for the author's own and other Agents' shared records, real recall with compound
scopes, multi-page shared-document retagging, and invalidation of legacy private
observations after retagging and re-consolidation.

The Agent and Organization Memory viewers' list contract (tag-filtered items and total, search, and
pagination) is proven against the same pinned image running with its embedded database
and mock extraction model, in
`../../api/tests/integration/test_agent_memory_viewer_contract.py`; its stand-in tests
cover authorization and failure handling. Pull or build the image first when absent.

The Hermes and OpenClaw telemetry plugins run inside agent containers but are
delivered from repository source through runtime configuration, rather than as
importable API modules. Tests load them from their source paths and call their
hooks directly. Shared setup lives in
`../../api/tests/helpers/telemetry_plugins.py`.

- Assert on the payload a plugin **posts**, not on its internal buffer, and
  validate it against the real ingest models so the two halves cannot drift.
- The OpenClaw plugin is JavaScript, so its tests drive it as a `node`
  subprocess against a throwaway HTTP listener, following the same
  subprocess-and-real-HTTP pattern as `../../api/tests/unit/test_healthz_server_metrics.py`.
  `node` is required; a missing `node` MUST fail rather than skip.
- The healthz `/metrics` tests run both runtimes' scripts over a fake cgroup directory
  (`HEALTHZ_CGROUP_ROOT`) and compare their output, so the two cannot drift.
  `../../api/tests/integration/test_resource_usage_prometheus_contract.py` goes further:
  a real Prometheus (image `TESTCONTAINERS_PROMETHEUS_IMAGE`, default the pin in
  `../../helm/monitoring/tests/run.sh`) scrapes the real script with basic auth on, and
  the queries are read back through the API's own client. It needs Docker to reach the
  host through `host.docker.internal`.
- Fakes of runtime objects can only prove our own logic. Anything that depends
  on runtime behavior MUST also be checked inside the pinned image. The Hermes
  SessionStore, PVC, native Telegram access, Teams runtime webhook, and image smoke contracts run through
  `../../hermes-base/test-image.sh`, invoked by
  `../../.github/workflows/hermes-base.yml`. Both that workflow and
  `../../.github/workflows/openclaw-base.yml` smoke-test their base images. CI
  selects the matching workflow using the path triggers documented in
  [CONTRIBUTING.md](../../CONTRIBUTING.md#open-a-pull-request).
- `../../hermes-base/test-image.sh` and `../../openclaw-base/test-healthz-metrics.sh`
  run each healthz script in its pinned image under `--memory 1g --cpus 0.5`, as the
  image's own user, and check the CPU and memory it reports. Whether the cgroup files
  exist and are readable to that user depends on the image, not on our code.
- `../../openclaw-base/test-startup.sh` proves OpenClaw startup behavior in the
  pinned image: a legacy workspace PVC migrates with `doctor --fix` and a clean
  one never runs doctor, and a stale PVC heartbeat is replaced and stays
  disabled through validation and doctor.
- `../../hermes-base/test-image.sh` is the single entrypoint for Hermes image
  verification. It runs the image smoke test, builds the real Deployment spec
  and exercises its init container against a fresh root-owned Docker volume,
  verifies non-root writes to startup state and workspace, drives each native
  Telegram access policy through the pinned adapter and gateway authorization
  chain, pins the Teams runtime listener's environment/port/path contract, and runs
  the telemetry plugin against the real SessionStore. The workflow invokes this
  entrypoint when either the Hermes builder or base image changes.
- `../../api/tests/fixtures/test-messaging-retirement.sh` exercises fresh, upgraded,
  and restored persistent state using generated configuration in both pinned images.
  It covers malformed-job isolation, managed files, inactive/main-session jobs, effective
  home targets, and rejection of stale saved defaults after OpenClaw configuration merge.
  Hermes image tests also drive native origin/home scheduled delivery and silence.
  `../../openclaw-base/test-native-runtime.sh` checks native one-shot scheduling,
  observer hooks, retirement, and native `message`/`cron` tool access. Its pinned-image
  message fixture uses the real tool factory/filter and dry-run sends for replies
  to an existing message and other channels, and verifies native context restrictions.
  Upgraded/restored state retains unrelated tool denies and message policy while
  removing the stale `message` deny. Hermes checks that its send engine is absent
  from the agent tool registry. Scheduler fixtures simulate model/provider execution;
  message fixtures use dry runs. These checks send no live provider messages.
- The separate `../../api/runtime_tests/` pytest suite starts Agent Barn's
  generated runtime configuration in the real image and proves materialized
  Agent Skills are visible through Hermes' `skills_list` and `skill_view`. The
  workflow runs it against the same image after the image contract tests.
- Both runtime workflows run the Agent Memory contracts against their built image.
  Use `HERMES_TEST_IMAGE=<image> make test-api-runtime` or
  `OPENCLAW_TEST_IMAGE=<image> make test-api-runtime RUNTIME=openclaw`. These prove
  the real provider loader and hooks recall and retain alongside native memory,
  replace stale settings, avoid persisting credentials, and disable Hindsight on
  the same volume. Hermes exercises its actual turn loop with a deterministic
  streaming model endpoint; OpenClaw exercises its core hook runner directly.

## UI and browser tests

Changed UI behavior SHOULD include Playwright coverage when regression risk is non-trivial.

Use this ownership split:

- Specs and assertions: `../../ui/tests/e2e/`
- Selectors and user interactions: `../../ui/tests/pages/`
- Request interception and reusable mocks: `../../ui/tests/pages/data-support/`
- Static response data: `../../ui/tests/fixtures/`

Page objects expose user-level actions and stable locators; specs describe behavior and outcomes. Keep mock setup out of specs when a shared domain support helper can own it.

Prefer selectors in this order:

1. Accessible role/name.
2. Label or visible text with stable meaning.
3. Existing test ID when semantic selectors are insufficient.

Avoid assertions inside page objects. Avoid feature-specific network interception copied across specs. Update Zod schemas, hooks, mock responses, and Playwright expectations together when an API response contract changes.

## Selecting coverage by change

| Change                       | Minimum verification                                          |
| ---------------------------- | ------------------------------------------------------------- |
| API business rule            | Service/unit coverage plus integration behavior               |
| API route/auth contract      | Integration test                                              |
| Database schema              | Migration plus integration coverage                           |
| Parser or runtime builder    | Focused unit tests; integration where wiring matters          |
| Runtime plugin behavior      | Unit tests asserting the posted payload; add a pinned-image contract when behavior depends on runtime internals |
| UI interaction or navigation | Playwright when regression risk is meaningful                 |
| UI schema/query hook         | Typecheck, lint, and focused browser coverage                 |
| Helm/Kubernetes behavior     | Chart/render checks and Kubernetes integration when available |
| Contributor-facing documentation only | Link/path/format validation; application tests are optional |

Platform Agent Memory model changes require settings API authorization and
failure-atomicity tests, browser selection/save/retry and Organization Owner
denial tests, and the pinned Hindsight provider contract. That contract records
actual outgoing models for new and in-progress operations, tool calls, and
concurrent bank attribution. Run `make check-memory` for bridge/chart wiring and
`make check-migrations` for the singleton settings migration.

## Failure handling

Fix failures introduced by the change. If an unrelated pre-existing failure blocks verification, report the exact command and failure without reshaping unrelated code to make the suite green.
