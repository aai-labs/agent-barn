# Contributing to Agent Barn

Thanks for considering a contribution. Agent Barn is an open-source control plane for AI agents, maintained by [AAI Labs UAB](https://aai-labs.com). The repository is `aai-labs/agent-barn`.

This document covers how to report problems, propose changes, and get a pull request merged.

## Table of contents

- [Ways to contribute](#ways-to-contribute)
- [Where to ask questions](#where-to-ask-questions)
- [Reporting bugs](#reporting-bugs)
- [Proposing features](#proposing-features)
- [Development setup](#development-setup)
- [Project structure](#project-structure)
- [Making a change](#making-a-change)
- [Commit messages](#commit-messages)
- [Pull requests](#pull-requests)
- [Review process](#review-process)
- [Coding standards](#coding-standards)
- [Tests](#tests)
- [Documentation](#documentation)
- [Contributing a template or skill](#contributing-a-template-or-skill)
- [Security](#security)
- [Licensing and sign-off](#licensing-and-sign-off)
- [Contributor role in Discord](#contributor-role-in-discord)
- [Code of Conduct](#code-of-conduct)

## Ways to contribute

You do not need to write code to be useful here.

| Contribution                         | Where it goes                                                |
| ------------------------------------ | ------------------------------------------------------------ |
| Bug report                           | GitHub Issues                                                |
| Feature proposal                     | GitHub Discussions first, then an Issue                      |
| Documentation fix                    | Pull request                                                 |
| New agent template or skill          | Pull request, see [below](#contributing-a-template-or-skill) |
| Answering questions from other users | Discord `#support`                                           |
| Triaging existing issues             | GitHub Issues                                                |

## Where to ask questions

Do not open an issue to ask a question.

| What                                           | Where                                          |
| ---------------------------------------------- | ---------------------------------------------- |
| Setup help, config questions, "is this a bug?" | Discord `#support`                             |
| Confirmed bugs                                 | GitHub Issues                                  |
| Feature requests and design debate             | GitHub Discussions                             |
| Security vulnerabilities                       | See [Security](#security). Never post publicly |

A maintainer responds to every Discord `#support` post within 3 business days.

## Reporting bugs

Search existing issues first, including closed ones.

A good report includes:

- The commit or image tag you are running (there is no single product version number; see [SECURITY.md](SECURITY.md#supported-versions))
- Deployment method: `make up` locally, or Helmfile on Kubernetes
- Environment: OS, Kubernetes version if relevant
- Which chat platform and runtime, if the bug involves a running agent (Slack, Teams, Telegram, or Discord; Hermes or OpenClaw)
- What you expected to happen
- What actually happened
- Minimal steps to reproduce
- Relevant logs or error output, secrets redacted

Reports without a reproduction usually stall. If you are not sure whether something is a bug, ask in `#support` first and we will tell you.

## Proposing features

Open a GitHub Discussion before writing code. This is not bureaucracy, it is how you avoid spending a weekend on something we will not merge.

Include:

- The problem you are trying to solve, not the solution you have in mind
- Who has this problem
- What you currently do instead
- Rough shape of the change, if you have one

Once a maintainer confirms the direction, open an issue and link the discussion. Then start work.

Small, self-contained changes (a bug fix, a docs correction, a missing config validation) do not need this. Just open a PR.

## Development setup

**Prerequisites**

| Tool                                  | Version                                                   |
| ------------------------------------- | --------------------------------------------------------- |
| Python                                | 3.14, as pinned in `api/.python-version`                  |
| [uv](https://github.com/astral-sh/uv) | current                                                   |
| Node.js                               | 24 in CI, 20+ works locally                               |
| [pnpm](https://pnpm.io/)              | 11.17, as pinned by `packageManager` in `ui/package.json` |
| Docker                                | with Compose v2                                           |
| Make                                  | any                                                       |

Only needed if you touch deployment: `kubectl`, Helm 3, Helmfile 0.171+, and the `helm-diff` plugin.

**Get running**

```bash
git clone https://github.com/aai-labs/agent-barn.git
cd agent-barn

make setup          # cd api && uv sync; cd ui && pnpm install; copies .env.spec to .env
# fill in the required values in .env

make db-up          # PostgreSQL
make migrate        # Alembic upgrade head
make up             # db, redis, api, worker, ui — all hot-reloading
```

The API reads its configuration from the repository root `.env`, created from the tracked `.env.spec` template. Every value is commented there. The UI serves on `:3000`, the API on `:8000` with routes under `/api/v1`, and the separately mounted ingest app on `:8001`. Sign in with the `PLATFORM_ADMIN_CREDENTIALS` you set.

Prefer running on the host? Each target below watches its own source, so run the ones you need in separate terminals alongside `make db-up` (plus `make redis-up` for the worker).

**Common commands**

| Command                                                                       | What it does                                            |
| ----------------------------------------------------------------------------- | ------------------------------------------------------- |
| `make dev-api`                                                                | API on `:8000`, hot reload                              |
| `make dev-ui`                                                                 | UI on `:3000`, hot reload                               |
| `make dev-worker`                                                             | Dramatiq worker, hot reload; needs Redis                |
| `make up` / `make down` / `make restart`                                      | Full Docker stack, foreground                           |
| `make logs` / `make worker-logs`                                              | Tail logs                                               |
| `make clean`                                                                  | Tear down the stack and its volumes                     |
| `make migrate` / `make rollback` / `make makemigrations` / `make merge-heads` | Alembic                                                 |
| `make check-api` / `make fix-api`                                             | Ruff check, format check, and `ty` type check / autofix |
| `make lint-ui` / `make check-ui`                                              | ESLint / TypeScript                                     |
| `make test-api` / `make test-api-k8s` / `make test-ui`                        | Test suites                                             |
| `make coverage`                                                               | API coverage report                                     |
| `make reconcile`                                                              | One-shot repair pass for stuck event deliveries         |

If `make setup` fails, post in `#support` with the output. Setup breakage is our bug, not yours.

More detail on local development, migrations, and releases: [`docs/guidelines/operations.md`](docs/guidelines/operations.md).

## Project structure

```
/api            FastAPI control plane, Dramatiq worker, ingest app
  /domains      one package per domain: routes, service, repository, models
  /infrastructure  adapters: Kubernetes, Slack, Telegram, Discord, LiteLLM, email, crypto
  /migrations   Alembic revisions
  /tests        unit and integration suites
/ui             Next.js App Router frontend
  /src/features feature-first UI code
  /src/shared   transport and query infrastructure
  /tests        Playwright specs, page objects, fixtures
/helm           one chart per deployed service
/k8s            cluster prerequisites the charts don't own
/hermes-base    Hermes agent base image
/openclaw-base  OpenClaw agent base image
/docs           architecture, features, guidelines, ADRs
compose.yml            local dev stack
helmfile.yaml.gotmpl   release ordering and values for deployment
deploy.sh              helmfile sync driven from .env.deploy
```

`AGENTS.md` holds the repository-wide engineering rules, `CONTEXT.md` the domain glossary, and [`docs/INDEX.md`](docs/INDEX.md) routes you to the right guideline for whatever you are changing. Read the routed document before a non-trivial change; reviewers treat it as the current contract.

## Making a change

1. Check for an existing issue. If none exists and the change is non-trivial, open one.
2. Comment on the issue to claim it, so two people do not do the same work.
3. Fork the repo and create a branch off `staging`.
4. Make your change.
5. Add or update tests.
6. Update documentation if behaviour changed.
7. Run the checks for the areas you touched (see [Tests](#tests)).
8. Open a pull request against `staging`.

`staging` deploys to the staging namespace and is promoted to `main` by a maintainer; `main` deploys production. Target `main` directly only for a hotfix a maintainer has asked for.

**Branch naming**

```
fix/helm-imagepullbackoff
feat/telegram-integration
docs/rbac-setup-guide
chore/bump-deps
```

Maintainers also use `AF-<number>-<slug>` for branches tracking an internal ticket. Either is fine.

**Good first issues**

Issues tagged [`good first issue`](https://github.com/aai-labs/agent-barn/labels/good%20first%20issue) are scoped small and have enough context to start without asking. If one is unclear, say so in the issue and we will improve it.

Issues tagged [`help wanted`](https://github.com/aai-labs/agent-barn/labels/help%20wanted) are larger and unclaimed.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) for new work. History predates the convention and is mixed; that is not a licence to add to the mess.

```
<type>(<scope>): <short description>

<optional body>

<optional footer>
```

| Type       | Use                                    |
| ---------- | -------------------------------------- |
| `feat`     | New functionality                      |
| `fix`      | Bug fix                                |
| `docs`     | Documentation only                     |
| `test`     | Tests only                             |
| `refactor` | No behaviour change                    |
| `perf`     | Performance                            |
| `chore`    | Tooling, dependencies, CI              |
| `breaking` | Use `!` after type, e.g. `feat(api)!:` |

Examples:

```
fix(helm): correct image repository for the API chart
feat(agents): add Discord channel allowlist
docs(rbac): document the org-level model allowlist
```

Reference issues in the body or footer: `Closes #123`. Internal tickets go there too: `AF-256`.

## Pull requests

**Before you open one**

- [ ] Checks pass locally for the areas you touched: `make check-api`, `make test-api`, `make lint-ui`, `make check-ui`, `make test-ui`
- [ ] Schema changes include an Alembic migration, and `make check-migrations` reports exactly one head
- [ ] Tests added or updated
- [ ] Docs updated if behaviour, an invariant, or an operational contract changed
- [ ] Chart `version` bumped in `helm/<chart>/Chart.yaml` if you changed that chart's templates or values
- [ ] Commits follow Conventional Commits
- [ ] Commits are signed off (see [sign-off](#licensing-and-sign-off))
- [ ] Branch is rebased on current `staging`

**In the PR description**

- What changed and why
- Link to the issue or discussion
- How you tested it
- Screenshots or terminal output for UI changes
- Any breaking changes, called out explicitly

CI is path-aware: touching `api/` runs the API lint, migration, and test jobs; `ui/` runs ESLint, the type check, and Playwright; the base-image directories and their telemetry plugins rebuild and smoke-test the runtime images; `helm/monitoring/**` unit-tests the alert rules.

**Keep PRs small.** A 200-line PR gets reviewed in a day. A 2000-line PR sits for a week. If your change is large, split it: refactor first, feature second.

Draft PRs are welcome. Open one early if you want direction before finishing.

## Review process

| Stage              | What happens                                                          | Typical time         |
| ------------------ | --------------------------------------------------------------------- | -------------------- |
| CI                 | Lint, type checks, tests, and image builds run for changed components | Minutes              |
| First review       | A maintainer reads it and responds                                    | 3 business days      |
| Iteration          | You address comments, push updates                                    | Yours                |
| Approval and merge | Squash merge into `staging`                                           | Same day as approval |

Reviewers check the routed documentation as well as the diff: a changed invariant, boundary, state model, or operational contract has to move its authoritative document in the same PR. Any change that reads or writes an agent or a subordinate resource is also checked against [`docs/features/rbac/IMPLEMENTATION-BRIEF.md`](docs/features/rbac/IMPLEMENTATION-BRIEF.md), even when the PR is not framed as an RBAC change.

If your PR has had no response after 5 business days, comment on it or post in Discord `#contributing`. Chasing is fine. That is a failure on our side, not impatience on yours.

We may decline a PR. If we do, we will say why. Usually it is scope, maintenance burden, or a conflict with the roadmap, and it is rarely about code quality.

## Coding standards

- Formatting and linting are enforced by Ruff (`make fix-api`) and ESLint. Do not argue with the formatter.
- API dependencies flow routes → services → repositories. No business workflows in routes, no SQL in services.
- UI code is feature-first under `ui/src/features/`; all HTTP goes through `ui/src/shared/api`.
- Preserve tenant isolation and the agent access checks. A repository query that forgets the accessible-agent join is the most common regression here.
- Follow existing patterns in the file you are editing over general best practice.
- Errors are wrapped with context, not swallowed.
- No new dependencies without a note in the PR describing why. Every dependency is a long-term liability.
- No secrets, credentials, tokens, or internal hostnames anywhere in the repo, including tests and fixtures.
- Record an ADR under `docs/adr/` only when the choice is hard to reverse, surprising without context, and based on a real trade-off. Never invent the rationale.

Full rules: [`docs/guidelines/code.md`](docs/guidelines/code.md) for the API, [`docs/guidelines/webapp.md`](docs/guidelines/webapp.md) for the UI.

## Tests

| Type                   | Location                                          | Run with            |
| ---------------------- | ------------------------------------------------- | ------------------- |
| API unit               | `api/tests/unit/`                                 | `make test-api`     |
| API integration        | `api/tests/integration/`                          | `make test-api`     |
| Kubernetes integration | `api/tests/integration/test_kubernetes_client.py` | `make test-api-k8s` |
| Browser end-to-end     | `ui/tests/e2e/`                                   | `make test-ui`      |

Integration tests run the real FastAPI app against a migrated PostgreSQL from Testcontainers, so Docker has to be running. They follow a Given/When/Then style with PyHamcrest matchers rather than bare `assert`. Playwright specs live in `ui/tests/e2e/`, with selectors in `ui/tests/pages/` and mocks in `ui/tests/pages/data-support/`.

Bug fixes need a regression test that fails before your fix and passes after. New behaviour needs the happy path, the authorization and tenancy failures, key validation failures, and not-found or conflict behaviour. Schema changes need migration coverage.

Run the smallest complete set for what you touched before widening. If something is genuinely hard to test, say so in the PR rather than skipping it silently. Details and worked examples: [`docs/guidelines/testing.md`](docs/guidelines/testing.md).

## Documentation

Docs live in `/docs` and are part of the change, not a follow-up.

Update the routed feature or architecture document when you change behaviour, an invariant, a boundary, a state model, or an operational contract, and update [`docs/INDEX.md`](docs/INDEX.md) when a document, domain, UI feature, or runtime is added, removed, renamed, or moved. A feature that is not documented does not exist to users.

Docs-only PRs are welcome and get reviewed fast.

## Contributing a template or skill

**An agent template** is a directory under `api/domains/templates/predefined/seeds/`, named for its stable key, containing:

| File               | Purpose                                                                                                        |
| ------------------ | -------------------------------------------------------------------------------------------------------------- |
| `settings.yaml`    | `name`, `description`, and `required_skills` (a bare skill name, or `any_of:` for an either/or group)          |
| Markdown artifacts | Any of `soul.md`, `identity.md`, `user.md`, `tools.md`, `agents.md`, `boot.md`, `bootstrap.md`, `heartbeat.md` |

Anything you omit falls back to the shared file in `seeds/_defaults/`, so a focused template only ships the artifacts that differ. These files feed the one-time bootstrap of a platform lineage; once it exists in the database, further versions are authored through the admin draft flow, not by editing the seed. Read [`docs/features/templates-and-skills.md`](docs/features/templates-and-skills.md) and the [file-based bootstrap ADR](docs/adr/2026-08-03-platform-template-file-based-bootstrap.md) first.

**A skill** is a module under `api/domains/agents/aai_cli_skills/` exporting the Markdown docs an agent gets, registered in `AAI_CLI_PROVIDER_SKILLS` with the credential providers it requires and a `tools_pointer` line. A skill for a provider we do not support yet also needs a `SecretProvider` enum value, a migration adding it to the database enum, and a credential validator under `api/infrastructure/integration_validators/`.

What we look for:

| Requirement           | Detail                                                                          |
| --------------------- | ------------------------------------------------------------------------------- |
| Scoped credentials    | Read-only by default. Document every permission the provider token needs        |
| Credential validation | A validator that fails clearly on a bad or under-scoped credential              |
| Error handling        | Fail loudly and clearly. Never fail silently                                    |
| Rate limit handling   | Respect upstream limits, back off                                               |
| Tests                 | Unit coverage under `api/tests/unit/`, upstream mocked, no live API calls in CI |
| Docs                  | Auth setup, config options, known limitations                                   |

Before building a skill for a third-party service, open a Discussion. We may already have one in progress, and integrations carry ongoing maintenance cost that we need to plan for.

## Security

**Do not open a public issue for a security vulnerability.**

Email [tadas@aai-labs.com](mailto:tadas@aai-labs.com), or use [GitHub private vulnerability reporting](https://github.com/aai-labs/agent-barn/security/advisories/new) on this repo. Both reach the same people.

Include:

- Description of the vulnerability
- Steps to reproduce
- Affected commit or image tag
- Impact assessment if you have one

We acknowledge within 3 business days and keep you updated until it is resolved. We credit reporters in the release notes unless you prefer otherwise. Full policy and scope: [SECURITY.md](SECURITY.md).

## Licensing and sign-off

Agent Barn is licensed under [Apache 2.0](LICENSE), in full. Contributions are made under the same licence. Third-party components keep the licence provided by their owner.

Sign off every commit:

```bash
git commit -s -m "fix(helm): correct image repository"
```

That adds a `Signed-off-by` line with your name and email. It is your statement that you wrote the code, or otherwise have the right to submit it under this licence.

To sign off commits you already made:

```bash
git rebase --signoff HEAD~<number-of-commits>
```

Set `user.name` and `user.email` in git first, or the line will be wrong:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

## Contributor role in Discord

Get a PR merged and you get the Contributor role in the [Agent Barn Discord](https://discord.gg/A3vJF5ZKnu). Post your merged PR link in `#contributing` and a maintainer will grant it.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). It applies to the repo, the issue tracker, and the Discord server.

Report violations to [tadas@aai-labs.com](mailto:tadas@aai-labs.com).

---

Questions about contributing that this document does not answer: ask in Discord `#contributing`. If you had the question, someone else has it too, and we will fix this file.
