# API Architecture

## Read when

Read before changing API composition, dependency injection, route/service/repository boundaries, tenancy, transactions, migrations, or API test infrastructure.

## Composition and layering

The API has two composition roots. `../../api/api_app.py` mounts product routes at `/api/v1`, attaches the Injector, configures CORS, and defines the database-backed health check. `../../api/ingest_app.py` mounts runtime telemetry at `/ingest/v1`. `../../api/start.sh` serves the ingest app on port 8001 alongside the product API on port 8000.

The default dependency direction is:

```text
routes.py → service.py → repository.py → PostgresRepositoryDelegate
                     ↘ infrastructure adapters
```

- Routes authenticate, parse, delegate, and return.
- Services own business rules, permission-sensitive behavior, error translation, and cross-domain orchestration.
- Repositories own SQLModel/SQLAlchemy queries and persistence behavior.
- Infrastructure adapters own PostgreSQL, Kubernetes, email, Slack, LiteLLM, OpenRouter, crypto, and related external concerns.

Nearby domains are the implementation template. Costs and Ingest intentionally differ from CRUD-shaped domains, while Agents has additional route, builder, artifact, and runtime files.

## Tenancy and authorization

Authentication builds `CurrentUserContext`; organization-scoped services derive the active organization from it. `X-Organization-Id` selects the active organization, with the configured default organization as fallback. Normal users require membership. Tenant resolution synthesizes owner-level organization context for superusers, and authorization helpers explicitly preserve the superuser bypass.

The active Membership's fixed Organization Role is resolved through an immutable code-owned Permission mapping on each request. Organization Roles govern Organization, Membership, Template, Skill, and Organization-summary capabilities; protected Organization Owner recovery actions remain explicit governance invariants. Database-backed Agent Access Roles separately govern one Agent aggregate, while Organization Owner/Admin and superuser in explicit Organization context have implicit Agent Owner authority. Agent user-facing queries apply visibility in repositories before count and pagination, and Agent services use the shared authorization module for effective operations and action checks. Runtime Ingest and Teams webhook authentication remain separate non-user boundaries.

Tenant-sensitive reads generally return 404 when a resource is absent, belongs to another Organization, or is outside the caller's Agent Access visibility. A visible resource with a missing action Permission returns 403. Organization administration retains its documented 403 behavior. The integration contract is exercised in `../../api/tests/integration/test_cross_org_isolation.py`, `../../api/tests/integration/test_tenant_resolution.py`, and `../../api/tests/integration/test_agent_rbac.py`.

## Persistence and transactions

Most repositories reuse `../../api/infrastructure/postgres/repository.py`. Delegate operations open and commit a session per operation. A service workflow spanning several repository calls is therefore not automatically atomic; workflows requiring all-or-nothing behavior need an explicit repository transaction boundary.

Database records generally inherit UUID and timestamp fields from `../../api/infrastructure/postgres/models.py`. Schema evolution belongs in `../../api/migrations/versions/`; integration setup applies Alembic heads to a PostgreSQL test container.

## Startup data

The application lifespan ensures the default superuser and organization, records their owner membership, seeds built-in aai-cli skills, and seeds predefined templates. Changes to bootstrap entities can affect startup, tests, and predefined catalog behavior simultaneously.

## Testing

- Integration tests use the real FastAPI app and migrated PostgreSQL with additive Injector overrides.
- Unit tests cover services, repositories, parsers, builders, and infrastructure clients.
- API behavior tests follow the repository's Given/When/Then step style.
- Prefer `make check-api` and `make test-api`; Kubernetes integration has its separate target.

## Source map

| Concern | Source |
|---|---|
| Product API composition and router registry | `../../api/api_app.py` |
| Ingest API composition and process entry | `../../api/ingest_app.py`, `../../api/ingest_main.py`, `../../api/start.sh` |
| Injector configuration | `../../api/core/utils.py`, `../../api/infrastructure/app.py` |
| Auth and tenant resolution | `../../api/domains/auth/utils.py`, `../../api/domains/auth/models.py` |
| Permission and Agent authorization | `../../api/domains/rbac/catalog.py`, `../../api/domains/rbac/policy.py`, `../../api/domains/agents/authorization.py` |
| Shared persistence delegate | `../../api/infrastructure/postgres/repository.py` |
| Base database model | `../../api/infrastructure/postgres/models.py` |
| Migrations | `../../api/migrations/versions/` |
| Test app and database setup | `../../api/tests/conftest.py`, `../../api/tests/core/` |

## Change impact

When adding or moving a product router, update `../../api/api_app.py`; ingest routes are registered through `../../api/ingest_app.py`. When a schema changes, update the database model, API DTO where required, migration, integration tests, and corresponding UI Zod schema. When a workflow spans repositories, verify whether partial persistence is acceptable before relying on the default session-per-operation behavior.
