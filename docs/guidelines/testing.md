# Testing guidelines

## Core principles

- Changed behavior needs coverage at the lowest layer that proves the contract reliably.
- Test happy paths, authorization/permission failures, important validation failures, and not-found/conflict behavior.
- Regression fixes SHOULD include a test that fails for the original defect.
- Keep setup reusable, interactions centralized, and assertions close to the behavior being specified.
- Run repository `make` targets when available.

## Verification commands

From the repository root:

```bash
make check-api       # Ruff check/format check and Python type checking
make fix-api         # Ruff autofix and formatting
make test-api        # API tests excluding Kubernetes integration
make test-api-k8s    # Kubernetes integration tests
make coverage        # API coverage
make lint-ui         # ESLint
make check-ui        # TypeScript type check
make test-ui         # Playwright
```

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

Integration tests use the real FastAPI app, migrated PostgreSQL, and additive Injector overrides. Follow the existing Given/When/Then style in `../../api/tests/integration/`:

- `given(...)` assembles reusable setup steps.
- `when(...)` names the action.
- `then(...)` contains assertions.
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
