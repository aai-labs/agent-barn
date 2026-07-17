# Agent work loop

1. **Context** — Read the task-specific guidance below, inspect neighboring code, and clarify material ambiguity before large edits.
2. **Plan** — Keep the approach scoped to the requested behavior; identify contracts, migrations, tests, and release impact before implementation. For work spanning multiple tickets or PRs, follow `docs/guidelines/epics.md`.
3. **Implement** — Follow established domain and feature boundaries; avoid unrelated refactors.
4. **Verify** — Run the checks in `docs/guidelines/testing.md` for every touched area and fix failures introduced by the change.
5. **Document** — Update agent-facing docs when domain language, invariants, boundaries, state models, or change-impact surfaces change.
6. **Release** — Apply `docs/guidelines/operations.md` version rules only when release preparation is requested.

## Context routes

| When working on                                                          | Read first                      |
| ------------------------------------------------------------------------ | ------------------------------- |
| Domain terminology                                                       | `CONTEXT.md`                    |
| Product behavior, architecture, or cross-domain changes                  | `docs/INDEX.md`                 |
| API routes, services, repositories, models, authorization, or migrations | `docs/guidelines/code.md`       |
| Next.js routes, React components, queries, providers, or API schemas     | `docs/guidelines/webapp.md`     |
| Tests, coverage, lint, type checking, or verification                    | `docs/guidelines/testing.md`    |
| Multi-ticket or multi-PR epic coordination                               | `docs/guidelines/epics.md`      |
| Local setup, migrations, deployment, Helm, or release versions           | `docs/guidelines/operations.md` |

Follow pointers in `docs/INDEX.md` before changing agent lifecycle, tenancy, templates/skills, activity ingest, integrations, costs, UI providers, or runtime/deployment behavior.

## Guardrails

- **Always** — Follow `MUST` rules in the routed guideline; preserve tenant isolation; use repository `make` targets when available; keep the diff scoped.
- **Clarify** — Resolve ambiguous authorization, lifecycle, ownership, or schema behavior before implementation.
- **Never** — Put business workflows in routes, SQL in services, ordinary UI calls outside `ui/src/shared/api`, reuse an immutable `appVersion`, or invent rationale for an ADR.

`MUST` is mandatory unless the user explicitly requests otherwise. `SHOULD` is the strong default. `MAY` is optional.

## Review protocol

Review agents MUST treat the routed documentation as review input, not optional background:

1. Map changed files and behaviors through `docs/INDEX.md`.
2. Read every applicable guideline, feature document, architecture document, glossary term, and related ADR before judging the diff.
3. Check both implementation correctness and documentation synchronization. A changed invariant, boundary, state model, or operational contract requires the authoritative document to change in the same diff.
4. Cite the relevant documentation path and rule for each documentation-based finding.
5. Treat documented behavior as the current contract, not an immutable one. When a change intentionally revises that contract, verify that code, tests, and docs move together instead of demanding the old behavior.

For a PR belonging to an active multi-PR epic, reviewers MUST also verify that `docs/features/<epic-slug>/CHANGELOG.md` records the delivered slice and resulting current state.

## Coding core

API dependencies flow routes → services → repositories. UI code is feature-first under `ui/src/features/`, with shared transport and query infrastructure under `ui/src/shared/`. Current system relationships belong in `docs/`; repeatable coding conventions belong in the routed guideline files.

## Maintaining guidelines

- Add repeatable API, UI, verification, and operational conventions to the matching file under `docs/guidelines/`.
- Keep each rule in one authoritative file; link instead of duplicating it.
- Update `docs/INDEX.md` when a routed document, domain, UI feature, runtime, or major responsibility is added, removed, renamed, or moved.
- Record an ADR under `docs/adr/` only when the choice is hard to reverse, surprising without context, and based on a real trade-off. Follow `docs/adr/README.md` and establish rationale from maintainers or historical evidence.

## Definition of done

- Behavior, validation, tenancy, and authorization cover important paths.
- Required tests and checks pass for touched areas.
- Schema changes include a migration.
- Agent-facing context remains accurate and discoverable.
- Release versions follow `docs/guidelines/operations.md` when applicable.
- The diff contains no unrelated churn.
