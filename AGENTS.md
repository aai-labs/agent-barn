# Agent work loop

1. **Context** — Load the task-specific sources below and inspect neighboring
   code before making substantial changes.
2. **Plan** — Keep the approach scoped; identify affected contracts, migrations,
   verification, documentation, and release impact. Use
   `docs/guidelines/epics.md` for work spanning multiple tickets or pull
   requests.
3. **Implement** — Follow the routed domain and feature boundaries and avoid
   unrelated refactors.
4. **Verify** — Select checks from `docs/guidelines/testing.md` for every touched
   area and fix failures introduced by the change.
5. **Document** — Update the authoritative document when terminology,
   invariants, boundaries, state models, or change-impact surfaces change.
6. **Release** — Apply `docs/guidelines/operations.md` version rules only when
   release preparation is requested.

## Sources of truth

- `CONTRIBUTING.md` owns the public contribution process.
- `CONTEXT.md` owns domain terminology.
- `docs/INDEX.md` routes product, architecture, feature, and engineering
  context.
- `docs/guidelines/code.md` owns API structure and layering;
  `docs/guidelines/webapp.md` owns UI feature structure and shared-client
  boundaries.
- `docs/guidelines/testing.md` owns verification guidance;
  `docs/guidelines/operations.md` owns local setup, migrations, deployment, and
  releases.
- `docs/adr/README.md` owns ADR qualification and format.

## Repository-wide guardrails

- `MUST` is mandatory unless the user explicitly requests otherwise. `SHOULD`
  is the strong default; `MAY` is optional.
- Keep the diff scoped, use repository `make` targets when available, and never
  commit secrets, credentials, or tokens.
- Preserve tenant isolation. Any surface that accesses or mutates an Agent or a
  subordinate resource must follow
  `docs/features/rbac/IMPLEMENTATION-BRIEF.md`.
- Resolve ambiguous authorization, lifecycle, ownership, or schema behavior
  before implementation.
- Respect the API and UI boundaries in their routed guidelines.
- Do not invent ADR rationale; establish it from maintainers or historical
  evidence and follow `docs/adr/README.md`.

## Review protocol

Reviewers must:

1. Map changed files and behavior through `docs/INDEX.md` and read every routed
   contract before judging the diff.
2. Check implementation correctness and documentation synchronization. When a
   change intentionally revises a documented contract, code, tests, and docs
   must move together.
3. Cite the relevant path and rule for every documentation-based finding.
4. Apply the RBAC brief to every Agent or subordinate-resource surface.
5. Apply the review requirements in `docs/guidelines/epics.md` to every pull
   request in an active multi-PR epic.

## Documentation ownership

Current behavior belongs in `docs/features/` or `docs/architecture/`,
repeatable engineering conventions in `docs/guidelines/`, terminology in
`CONTEXT.md`, and decision rationale in `docs/adr/`. Keep each fact or rule in
one authoritative file and link to it elsewhere.

Changes to scripts, Make targets, dependencies, CI, deployment or release
behavior, and public project policy MUST update the owning contributor-facing
document in the same change whenever its guidance would otherwise become
inaccurate or incomplete.

Update `docs/INDEX.md` when a routed document, domain, UI feature, runtime, or
major responsibility is added, removed, renamed, or moved.

## Definition of done

- Requested behavior, validation, tenancy, and authorization are covered.
- Checks selected by the testing guide pass.
- Schema and contract changes include their required migration and docs.
- Release versions follow the operations guide when applicable.
- The diff contains no unrelated churn.

## Work tracking

Public issues and proposals use GitHub Issues and Discussions as described in
`CONTRIBUTING.md`. The ignored `.scratch/` directory is for local working notes
only; it is not a contributor-facing source of truth.
