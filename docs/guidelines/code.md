# Code guidelines

## Project-defining rules

- API routes stay thin: authenticate, parse, delegate, return.
- Services own business rules, permission-sensitive behavior, and cross-domain orchestration.
- Repositories own query composition and persistence details.
- Reuse dependency injection and `PostgresRepositoryDelegate` unless a workflow needs explicit transaction control.
- Keep database models and API DTOs as distinct types.
- Keep changes scoped; broad refactors require an explicit request.

For current domain relationships and API runtime behavior, follow `../INDEX.md` rather than restating architecture here.

## Rule language

- `MUST`: mandatory unless the user explicitly requests otherwise.
- `SHOULD`: strong default; deviate only for a concrete reason.
- `MAY`: optional and situational.

## API domain structure

New domains live under `../../api/domains/<domain>/` with this baseline:

```text
models.py       # database models and request/response/filter DTOs
repository.py   # persistence and query behavior
service.py      # business rules and orchestration
routes.py       # HTTP handlers and dependency wiring
```

Add extra files only for a real responsibility such as exceptions, parsers, builders, or provider-specific behavior. Register product routers in `../../api/api_app.py`; Ingest routes use the separate composition described in `../architecture/api.md`.

Public service and repository methods MUST have explicit type hints. New abstractions SHOULD match the neighboring domain before introducing a new pattern.

## Layering and dependency injection

- Routes MUST NOT contain business workflows.
- Services MUST NOT embed SQL or query composition.
- Repositories MUST own database access and tenant-aware query behavior.
- Domain error translation SHOULD happen in services rather than routes.
- Reuse `injector` and `fastapi-injector`; do not construct domain dependencies inside handlers.
- Use `PostgresRepositoryDelegate` for ordinary session-per-operation persistence. Design an explicit transaction boundary when several writes must be atomic.

## HTTP semantics

Use:

- `200` for reads and updates returning a body.
- `201` for creates.
- `204` for deletes or actions returning no body.
- `400` for business precondition failures.
- `401` for unauthenticated requests.
- `403` for known but unauthorized operations.
- `404` for missing or tenant-hidden resources.
- `409` for state and uniqueness conflicts.
- `422` for schema-driven FastAPI/Pydantic validation.

Prefer `204` over ad hoc success objects such as `{"status": "ok"}`.

## Models and schema changes

- Name DTOs with `*Create`, `*Update`, `*Read`, and `*Filter` where applicable.
- Keep internal and encrypted fields out of response DTOs.
- Partial updates MUST use `exclude_unset=True` semantics.
- Mutable defaults MUST use `default_factory`.
- Database schema changes MUST include an Alembic migration.
- Treat PostgreSQL constraints, enum behavior, and migration order as part of the contract.

Before changing tenant ownership, authorization, or cross-domain relationships, follow the relevant route in `../INDEX.md`.

## Authorization enforcement

Any code that lets a user access, list, or mutate an Agent or a subordinate resource (conversations, tool calls, activity, logs, costs, Secrets, Skills, configuration) MUST enforce the permission-backed RBAC model in `../features/rbac/IMPLEMENTATION-BRIEF.md`, not just tenant isolation:

- Visibility MUST be enforced in the repository query (accessible-Agent join), never by fetching then filtering in the service.
- Mutations MUST check the actor's effective Permission through Organization authority or Agent Access, resolved fresh per request; never trust a cached role name or a client-supplied flag.
- New subordinate-resource endpoints MUST reuse the existing accessible-Agent query pattern rather than writing an independent visibility check.
- Use `404` for absent/inaccessible resources and `403` for visible-but-unauthorized operations, per the brief's HTTP semantics.

This applies even when the change looks unrelated to RBAC on its surface (e.g. a new activity or cost endpoint) — new resource surfaces are a common place for authorization gaps to slip in silently.

## API feature workflow

1. Update domain and API models.
2. Add repository behavior.
3. Add service logic and authorization.
4. Add or update thin routes.
5. Register a new router when needed.
6. Add a migration for schema changes.
7. Add tests following `testing.md`.
8. Run the API checks and tests listed in `testing.md`.
9. Apply service versioning rules from `operations.md` when release preparation is requested.

## Code style

- Follow Ruff formatting and lint rules.
- Prefer focused, domain-oriented functions and explicit types.
- Keep control flow direct; extract a module only when it creates a useful boundary.
- Use canonical domain terms from `../../CONTEXT.md`.
- Comments should explain a non-obvious constraint, not narrate the implementation.

## Review priorities

Review in this order:

1. Correctness and regressions.
2. Data-contract and schema safety.
3. Tenant isolation, authentication, and authorization, including Agent Access/Permission enforcement per `../features/rbac/IMPLEMENTATION-BRIEF.md` for any Agent or subordinate-resource surface, even when the diff is not framed as an RBAC change.
4. Transaction and external-system failure behavior.
5. Test coverage gaps.
6. Maintainability and style.

## Definition of done

- Behavior covers the happy path and important edge cases.
- Validation, tenancy, and authorization are correct.
- Required tests pass.
- Lint, formatting, and type checks pass for touched areas.
- Schema changes include a migration.
- Agent-facing docs are updated when invariants, boundaries, or state models change.
- Release versions are updated only when requested and according to `operations.md`.
- The diff contains no unrelated refactor or style churn.
