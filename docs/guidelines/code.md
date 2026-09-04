# Code guidelines

## Scope and context

For current domain relationships and API runtime behavior, follow
`../INDEX.md` rather than restating architecture here. Keep changes scoped;
broad refactors require an explicit request.

## API domain structure

New domains live under `../../api/domains/<domain>/` with this baseline:

```text
models.py       # database models and request/response/filter DTOs
repository.py   # persistence and query behavior
service.py      # business rules and orchestration
routes.py       # HTTP handlers and dependency wiring
```

Add extra files only for a real responsibility such as exceptions, parsers,
builders, or provider-specific behavior. Register product routers in
`../../api/api_app.py`, Ingest routers in `../../api/ingest_app.py`, and
Communications routers in `../../api/communications_app.py`. Their separate
composition roots are described in `../architecture/api.md`.

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

The permission-backed model in
`../features/rbac/IMPLEMENTATION-BRIEF.md` is authoritative for every surface
that accesses or mutates an Agent or subordinate resource. Read it before
designing the query, service permission check, or HTTP response.

## Code style

- Follow Ruff formatting and lint rules.
- Prefer focused, domain-oriented functions and explicit types.
- Keep control flow direct; extract a module only when it creates a useful boundary.
- Use canonical domain terms from `../../CONTEXT.md`.
- Comments should explain a non-obvious constraint, not narrate the implementation.
