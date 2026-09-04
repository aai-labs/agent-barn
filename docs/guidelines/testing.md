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

From the repository root:

```bash
make check-api       # Ruff check/format check and Python type checking
make fix-api         # Ruff autofix and formatting
make test-api        # API tests excluding Kubernetes integration
make test-api-k8s    # Kubernetes integration tests
make test-api-runtime # Runtime contracts against explicitly selected built images
make coverage        # API coverage
make lint-ui         # ESLint
make check-ui        # TypeScript type check
make test-ui         # Playwright
```

Runtime contracts require Docker and the image environment variable required
by the selected test, such as `HERMES_TEST_IMAGE`.

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

## Runtime plugin tests

The Hermes and OpenClaw telemetry plugins ship inside agent images rather than
being importable modules, so they are loaded from their source path and their
hooks are called directly. Shared setup lives in
`../../api/tests/helpers/telemetry_plugins.py`.

- Assert on the payload a plugin **posts**, not on its internal buffer, and
  validate it against the real ingest models so the two halves cannot drift.
- The OpenClaw plugin is JavaScript, so its tests drive it as a `node`
  subprocess against a throwaway HTTP listener, following the same
  subprocess-and-real-HTTP pattern as `../../api/tests/unit/test_healthz_server_metrics.py`.
  `node` is required; a missing `node` MUST fail rather than skip.
- Fakes of runtime objects can only prove our own logic. Anything that depends
  on runtime behavior MUST also be checked inside the pinned image — see the
  base-image smoke tests and the plugin-contract step in
  `../../.github/workflows/hermes-base.yml`. Those run on version bumps, which is
  when such assumptions break.
- The separate `../../api/runtime_tests/` pytest suite starts Agent Barn's generated runtime
  configuration in the real image and proves materialized Agent Skills are
  visible through Hermes' `skills_list` and `skill_view`. CI selects this
  workflow when the Hermes builder, startup scripts, or base image changes.

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
| Runtime plugin behavior      | Unit tests asserting the payload the plugin posts, plus a contract check inside the pinned runtime image |
| UI interaction or navigation | Playwright when regression risk is meaningful                 |
| UI schema/query hook         | Typecheck, lint, and focused browser coverage                 |
| Helm/Kubernetes behavior     | Chart/render checks and Kubernetes integration when available |
| Agent-facing docs only       | Link/path/format validation; application tests are optional   |

## Failure handling

Fix failures introduced by the change. If an unrelated pre-existing failure blocks verification, report the exact command and failure without reshaping unrelated code to make the suite green.
