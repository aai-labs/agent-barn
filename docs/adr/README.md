# Architectural Decision Records

ADRs preserve why consequential architectural choices were made. Current behavior belongs in `docs/features/` and `docs/architecture/`; implementation plans and backlog items belong elsewhere.

## Filename convention

Use:

```text
YYYY-MM-DD-descriptive-slug.md
```

The date is the decision date when known, or the retrospective record date. A descriptive slug keeps concurrent decisions merge-friendly without a shared number allocator.

Examples:

```text
2026-07-17-push-based-runtime-telemetry.md
2026-07-17-explicit-organization-context.md
```

## Qualification

Create an ADR only when the choice is:

1. Hard to reverse.
2. Surprising without context.
3. The result of a real trade-off.

Establish rationale from maintainers, issues, plans, commits, or other historical evidence. Label an ADR retrospective when it is written after implementation.

## Format

Start with the smallest complete record:

```markdown
# Decision title

Status: Accepted
Date: YYYY-MM-DD
Origin: optional ticket or historical source

One to three sentences stating the context, decision, and reason.
```

Add considered alternatives, consequences, or revisit conditions only when they help a future agent preserve or challenge the decision correctly.

Accepted ADR filenames remain stable. When a decision changes, create a new ADR and mark the old record as superseded.
