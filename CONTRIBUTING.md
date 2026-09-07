# Contributing to Agent Barn

Thanks for considering a contribution. Agent Barn is an open-source control plane
for AI agents, maintained by [AAI Labs UAB](https://aai-labs.com).

This file is the source of truth for the public contribution process. Detailed
engineering and operational instructions live in the documents linked below so
that commands and rules have one authoritative home.

## Find the right guide

| Need | Authoritative document |
| --- | --- |
| Run the project locally | [README quick start](README.md#quick-start) and [development guide](README.md#development) |
| Select and run checks | [Testing guidelines](docs/guidelines/testing.md) |
| Create migrations, deploy, or prepare a release | [Operations guidelines](docs/guidelines/operations.md) |
| Find the contract for an area of the codebase | [Documentation index](docs/INDEX.md) |
| Follow repository-wide engineering rules | [AGENTS.md](AGENTS.md) |
| Report a vulnerability | [Security policy](SECURITY.md) |
| Understand community expectations | [Code of Conduct](CODE_OF_CONDUCT.md) |

## Ways to contribute

You do not need to write code to help.

| Contribution | Where it goes |
| --- | --- |
| Confirmed bug | [GitHub Issues](https://github.com/aai-labs/agent-barn/issues) |
| Feature proposal or design discussion | [GitHub Discussions](https://github.com/aai-labs/agent-barn/discussions) |
| Documentation or code change | Pull request |
| Setup or configuration question | Discord [#support](https://discord.gg/A3vJF5ZKnu) |
| Security vulnerability | Private channels in the [security policy](SECURITY.md#reporting-a-vulnerability) |

Search existing issues and discussions before opening a new one. If you are not
sure whether a problem is a bug, ask in Discord first rather than opening an issue.

### Report a bug

Include enough information for another person to reproduce the problem:

- the commit or release tag you are running;
- how you started or deployed Agent Barn, such as `./run.sh`, native processes,
  or Helmfile;
- your operating system and Kubernetes version, when relevant;
- the chat platform and runtime, when an agent is involved;
- expected and actual behavior;
- minimal reproduction steps; and
- relevant logs with secrets removed.

### Propose a feature

Open a Discussion before implementing a substantial feature. Describe the problem,
who has it, the current workaround, and the rough shape of a possible change.
After maintainers confirm the direction, open or link an issue before starting.

Small, self-contained fixes do not need a design discussion.

## Prepare a contribution

Fork the repository, then create a branch from the current `staging` branch:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/agent-barn.git
cd agent-barn
git remote add upstream https://github.com/aai-labs/agent-barn.git
git fetch upstream
git switch -c docs/local-setup upstream/staging
```

Use a short branch name such as `fix/helm-image-pull` or
`docs/local-setup`. Maintainers may use internal ticket names; contributors do
not need one.

Follow the [quick start](README.md#quick-start) to configure and run the project.
Before changing code, read [AGENTS.md](AGENTS.md) and use
[docs/INDEX.md](docs/INDEX.md) to find the contracts for the area you are
touching.

Keep the change focused. Add regression coverage for bug fixes and tests for new
behavior. When an invariant, boundary, state model, or operational contract
changes, update its authoritative document in the same pull request.

Changes that expose, list, or mutate an Agent or one of its subordinate resources
must follow the authorization rules in
[the RBAC implementation brief](docs/features/rbac/IMPLEMENTATION-BRIEF.md).

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) for new commits:

```text
<type>(<optional-scope>): <short description>
```

Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, and `chore`.
Mark a breaking change with `!` and explain it in the commit body or a
`BREAKING CHANGE:` footer:

```text
feat(api)!: replace the legacy agent status response
```

Reference public issues in the body or footer, for example `Closes #123`.

## Open a pull request

Regular pull requests target `staging`. Target `main` only when a maintainer asks
you to prepare a hotfix. The `staging` and `main` branches deploy to separate
environments on the maintainers' k3s testing ground; version tags matching
`vX.Y.Z` deploy the hosted public release.

Before opening the pull request:

- update your branch from `upstream/staging`;
- run the complete checks selected by
  [the testing matrix](docs/guidelines/testing.md#selecting-coverage-by-change);
- include an Alembic migration for schema changes and follow the
  [migration workflow](docs/guidelines/operations.md#database-migrations);
- update the relevant documentation;
- apply the [release rules](docs/guidelines/operations.md#versioning-and-releases)
  when changing Helm packaging or a runtime base image; and
- inspect the final diff for secrets and unrelated changes.

In the pull request description, explain what changed and why, link the issue or
discussion, list the checks you ran, call out migrations and breaking changes,
and explain why any new dependency is needed. Include screenshots for visible UI
changes.

CI is path-aware. It runs API linting, migration checks, tests, and image builds
for API changes; ESLint, TypeScript, Playwright, and an image build for UI changes;
the matching Hermes or OpenClaw base-image workflow for base-image or
telemetry-plugin changes; and alert-rule tests for monitoring changes. Both
runtime workflows smoke-test their image, and Hermes also runs its pinned-image
plugin contract.

Maintainers review both the implementation and its routed documentation. Address
review comments by pushing updates to the same branch. A maintainer merges the
approved pull request into `staging`.

## Contribute a template or bundled skill

Discuss a new third-party integration before implementing it because each
integration adds credential and maintenance responsibilities.

### Agent templates

Predefined templates live under
`api/domains/templates/predefined/seeds/<stable-key>/`. Each template contains
`settings.yaml` and only the Markdown artifacts that differ from
`seeds/_defaults/`. Read
[the templates and skills contract](docs/features/templates-and-skills.md) and
[the bootstrap ADR](docs/adr/2026-08-03-platform-template-file-based-bootstrap.md)
before changing the seed format.

### Bundled skills

Each bundled aai-cli skill lives at
`api/domains/agents/aai_cli_skills/bundled/skills/aai-<integration>/SKILL.md`
and may include files under `references/`. Register its display name, command,
and credential providers in the corresponding maps in
`api/domains/agents/aai_cli_skills/__init__.py`; the registry builds
`AAI_CLI_PROVIDER_SKILLS` and the runtime `tools_pointer`.

A newly supported credential provider also requires the appropriate provider
model and migration plus a validator under
`api/infrastructure/integration_validators/`. Tests must mock upstream APIs and
cover credential validation, errors, and rate-limit behavior.

## Community, security, and licensing

The [Code of Conduct](CODE_OF_CONDUCT.md) applies to repository activity and
community spaces. Follow the [security policy](SECURITY.md) for private
vulnerability reporting; never disclose a vulnerability in a public issue.

Agent Barn is licensed under [Apache License 2.0](LICENSE). Contributions are
submitted under that license, while third-party components retain their own
licenses.

After your first pull request is merged, post its link in Discord
[#contributing](https://discord.gg/A3vJF5ZKnu) to request the Contributor role.
