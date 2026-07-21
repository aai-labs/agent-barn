# Multi-PR epic tracking

## Read when

Read before starting or contributing to an epic that spans multiple tickets or pull requests.

## Epic change log

Create one active coordination artifact at:

```text
docs/features/<epic-slug>/CHANGELOG.md
```

The epic change log connects slices that cannot be understood safely from one ticket or PR. It records what has landed, what contract is temporarily in transition, and what the next slice may assume.

Create it before the first implementation PR and update it in every PR belonging to the epic.

## Required content

```markdown
# Epic name — change log

Status: Active
Epic: <ticket or project link>
Related context: <feature, architecture, and ADR links>

## Current state

- Delivered: <capabilities already safe to depend on>
- In transition: <temporary compatibility or migration state>
- Next: <next unblocked slice>
- Blockers: <dependencies or decisions>

## Changes

### YYYY-MM-DD — TICKET — PR

- Delivered: <observable behavior or contract>
- Changed: <schema, API, UI, runtime, deployment, or docs>
- Follow-up: <remaining work or newly unblocked slice>
```

Keep `Current state` accurate and add change entries newest first. Link tickets and PRs rather than copying their full requirements.

## Boundaries

- Feature and architecture docs remain authoritative for current system behavior.
- ADRs remain authoritative for consequential decision rationale.
- The issue tracker remains authoritative for ownership, acceptance criteria, and backlog state.
- The epic change log owns only cross-ticket sequencing, temporary transition state, and delivered-slice history.
- Record observed outcomes rather than planned claims; mark unfinished work under `Next` or `Blockers`.

## Pull request and review behavior

Every epic PR MUST update the log with its delivered slice and resulting current state. Reviewers MUST treat a missing or inaccurate epic-log update as a documentation finding when the PR belongs to an active multi-PR epic.

A PR that changes an invariant, boundary, state model, or decision must also update the authoritative feature, architecture, or ADR document; the epic log does not replace those updates.

## Closing an epic

When the epic finishes:

1. Mark it `Completed` and record the final delivered state.
2. Move every durable fact into the relevant feature, architecture, glossary, guideline, or ADR document.
3. Resolve or move remaining work to the issue tracker.
4. Keep the log only when its staged migration or compatibility history remains useful; otherwise delete it and rely on Git and PR history.
