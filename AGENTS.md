# AGENTS.md

This file is the shared working agreement for AI/code agents contributing to this monorepo.

## Purpose

Write code that fits the established architecture and conventions so changes stay maintainable, testable, and predictable.

This repository contains:

- `api/`: FastAPI + SQLModel/SQLAlchemy + Alembic + injector + pytest + Ruff + uv.
- `ui/`: Next.js App Router + React + TypeScript + TanStack Query + Zustand + Zod + Playwright + pnpm.

API routes are mounted under `/api/v1`.

## Rule Language

- `MUST`: mandatory; do not deviate unless user explicitly requests it.
- `SHOULD`: strong default; deviate only with a clear reason.
- `MAY`: optional and situational.

## Core Commands

Run from repo root unless noted.

### Install Dependencies

- API: `cd api && uv sync`
- UI: `cd ui && pnpm install`

### Local Development

- API dev server: `make dev-api`
- UI dev server: `make dev-ui`
- Full docker stack: `make up`
- Stop stack: `make down`
- DB only: `make db-up`

### API Migrations

- Apply latest: `make migrate`
- Roll back one: `make rollback`
- Create migration: `make makemigrations`

### Tests

- API tests: `make test-api`
- API coverage: `make coverage`
- UI tests: `make test-ui`
- UI headed/debug (from `ui/`):
  - `pnpm test:watch`
  - `pnpm test:debug`

### Lint / Type / Checks

- API checks: `make check-api`
- API autofix: `make fix-api`
- UI lint: `make lint-ui`
- UI type check: `cd ui && pnpm -s tsc --noEmit`

Agents MUST prefer `make` targets when available.

## Repository Structure

### API

- `api/domains/<domain>/models.py`: domain/request/response models.
- `api/domains/<domain>/repository.py`: persistence/query logic.
- `api/domains/<domain>/service.py`: business logic and orchestration.
- `api/domains/<domain>/routes.py`: route handlers and dependency wiring.
- `api/infrastructure/`: shared infra (postgres delegate, email, app wiring).
- `api/migrations/versions/`: Alembic migrations.
- `api/tests/`: unit + integration + helpers.

### UI

- `ui/src/app/`: App Router routes and layouts.
- `ui/src/features/<feature>/`: feature-first domain code.
- `ui/src/auth/`: auth-specific domain logic.
- `ui/src/shared/api/`: API client/interceptors/errors.
- `ui/src/shared/query-keys.ts`: query key factory.
- `ui/tests/e2e/`: Playwright specs.
- `ui/tests/pages/`: page objects and test helpers.

## Creating New Domains (Required Playbook)

### API: New Domain

Agents MUST create API domain code under `api/domains/<domain>/` with this baseline:

```text
api/domains/<domain>/
  models.py
  repository.py
  service.py
  routes.py
```

Agents SHOULD only add extra files when needed (`exceptions.py`, builders, utilities).

Workflow for a new API domain:

1. Add request/response/domain models in `models.py`.
2. Add persistence/query methods in `repository.py`.
3. Add business rules and orchestration in `service.py`.
4. Add HTTP handlers in `routes.py`.
5. Register router in `api/api_app.py`.
6. Add migration if schema changed.
7. Add unit/integration tests.

API layering rules:

- Routes MUST stay thin (parse/deps/delegate/return).
- Services MUST own business rules and permission-sensitive logic.
- Repositories MUST own query and persistence details.
- Services MUST NOT embed SQL/query composition.
- Routes MUST NOT contain business workflows.

API coding style for new domains:

- File names MUST follow existing pattern: `models.py`, `repository.py`, `service.py`, `routes.py`.
- Public service/repository methods MUST include explicit type hints.
- Domain error translation SHOULD happen in services (not in routes).
- New abstractions SHOULD match nearby domain conventions before introducing a new pattern.

### UI: New Domain

Agents MUST create frontend feature code under `ui/src/features/<feature>/`.

Recommended baseline:

```text
ui/src/features/<feature>/
  schemas.ts
  hooks/
    use-<feature>-query.ts
    use-<feature>-actions.ts
  components/
    <feature>-grid.tsx
  utils.ts
```

Optional when needed:

- `providers/`
- `stores/`
- `constants.ts`
- `index.ts` (barrel export)

Workflow for a new ui feature domain:

1. Add Zod schemas and inferred types in `schemas.ts`.
2. Add or extend query keys in `ui/src/shared/query-keys.ts`.
3. Implement hooks with the shared API client.
4. Implement domain UI components.
5. Wire route usage under `ui/src/app/...`.
6. Add/update Playwright tests.

UI boundaries:

- Feature logic MUST live in `ui/src/features/*`.
- Shared folders SHOULD only contain reusable cross-domain concerns.
- Agents MUST NOT bypass `ui/src/shared/api` for normal app API calls.

UI coding style for new domains:

- File names SHOULD be `kebab-case`.
- React components MUST use `PascalCase`; hooks MUST use `use...` naming.
- Import order SHOULD be: external packages, `@/*` aliases, then relative imports.
- Hooks SHOULD return domain-friendly fields (`item`, `isLoadingItem`, `error`) instead of raw query objects when possible.

## API Conventions

### Architecture and DI

- Route handlers MUST be thin.
- Business logic MUST be in services.
- Query/persistence logic MUST be in repositories.
- Agents MUST reuse DI (`injector`, `fastapi-injector`) and existing wiring patterns.
- Agents MUST reuse `PostgresRepositoryDelegate` unless custom transaction control is required.
- New routers MUST be registered through `api/api_app.py`.

### HTTP Semantics

- `200` for reads/updates with body.
- `201` for creates.
- `204` for deletes/actions without body.
- `400` for business precondition failures.
- `401` for unauthenticated.
- `403` for unauthorized.
- `404` for missing/not visible.
- `409` for state/uniqueness conflicts.
- `422` SHOULD be schema-driven via FastAPI/Pydantic.

Agents MUST avoid ad hoc success payloads like `{"status": "ok"}` when `204` is appropriate.

### Models and Schema Rules

- DB models and API DTOs MUST stay separate.
- Names SHOULD follow `*Create`, `*Update`, `*Read`, `*Filter`.
- Internal-only fields MUST NOT leak in response models.
- Partial update flows MUST use `exclude_unset=True` semantics.
- Mutable defaults MUST use `default_factory`.

### API Coding Style

- Type hints MUST be explicit on public service/repository methods.
- Agents MUST follow Ruff formatting/lint rules.
- Functions SHOULD be focused and domain-oriented.
- Broad refactors SHOULD be avoided unless requested.

## UI Conventions

### Component and Routing Style

- Server Components SHOULD be default in `app/`.
- `"use client"` MUST only be added when needed (hooks/browser APIs/events/form/query hooks).
- Route-level loading for page-blocking navigation SHOULD use App Router `loading.tsx` at the appropriate segment.
- Route-level loading SHOULD represent router-owned waits, not unrelated client-only state that happens after the page has already rendered.
- Route-level failures for page-blocking requests SHOULD be handled with App Router `error.tsx` boundaries at the appropriate segment.
- Component-owned async data SHOULD render explicit inline error states instead of silently falling back to empty/loading UI forever.
- Internal imports MUST use `@/*` alias where practical.
- Existing UI primitives SHOULD be reused before creating new ones.

### Zod and Types

- Schemas MUST live near domain code.
- Schema + inferred type MUST be exported from same file.
- Important API responses MUST be Zod-validated.
- Agents MUST avoid duplicating interfaces that mirror schema-inferred types.

### API Client Rules

- Agents MUST use `ui/src/shared/api` client.
- Agents MUST NOT introduce ad hoc `fetch` wrappers or new axios instances for app API calls.
- Request/response camelCase/snake_case transformations SHOULD rely on existing client behavior.

### Query and Mutation Rules

- Query keys MUST use centralized helper patterns.
- Agents MUST NOT scatter literal ad hoc query keys.
- Mutations MUST invalidate affected list/detail keys.
- Hooks MUST use `enabled` guards when required params/context can be missing.
- Initial page-blocking fetches SHOULD fail at the route or segment layer when the page cannot render meaningfully without the data.
- Initial page-blocking fetches SHOULD also have a matching route-level loading state, not just a later component skeleton.
- Follow-up refetch/search/pagination work SHOULD usually keep its loading state local to the component instead of taking over the whole page.
- Follow-up query failures after a page has rendered SHOULD usually stay in component state with retry affordances, not escalate to full-page crashes.
- `useInfiniteQuery` SHOULD be preferred for progressive “load more” UIs.

### React Rules

- `useEffect` SHOULD NOT be used for derived render data.
- User-triggered flows MUST happen in handlers/mutation callbacks, not effect chains.
- Route-level loading SHOULD use `loading.tsx`.
- Subtree loading SHOULD use local `Suspense` boundaries.
- Client-provider fallbacks SHOULD be reserved for client-owned waits such as store hydration or post-render query state, not as a substitute for missing route loading.
- Error UI SHOULD distinguish auth/permission failures from general network/server failures when the API client exposes that information.

## Important Examples

### UI: Query Key + API Client + Zod Hook

```ts
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { createQueryKeyStructure } from "@/shared/query-keys";
import {
  organizationSchema,
  type Organization,
} from "@/features/organizations/schemas";

export const organizationKey = createQueryKeyStructure("organization");

export function useOrganization(organizationId?: string) {
  const query = useQuery({
    queryKey: organizationKey.detail(organizationId ?? ""),
    queryFn: () =>
      api.get<Organization>(`/api/v1/organizations/${organizationId}`, {
        schema: organizationSchema,
      }),
    enabled: !!organizationId,
  });

  return {
    organization: query.data?.data ?? null,
    isLoadingOrganization: query.isLoading,
    error: query.error,
  };
}
```

### UI: Mutation + Invalidation Pattern

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { organizationKey } from "@/shared/query-keys";

export function useOrganizationActions() {
  const queryClient = useQueryClient();

  const updateOrganization = useMutation({
    mutationFn: ({
      organizationId,
      payload,
    }: {
      organizationId: string;
      payload: Record<string, unknown>;
    }) => api.patch(`/api/v1/organizations/${organizationId}`, payload),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: organizationKey.lists() });
      queryClient.invalidateQueries({
        queryKey: organizationKey.detail(variables.organizationId),
      });
    },
  });

  return { updateOrganization };
}
```

### UI: App Router Error Boundary Pattern

```tsx
// app/dashboard/error.tsx
"use client";

import { RouteErrorState } from "@/components/route-error-state";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <RouteErrorState
      error={error}
      reset={reset}
      title="We couldn't load this dashboard page"
      description="A page-level request failed before the dashboard content could load."
    />
  );
}
```

### UI: App Router Loading Pattern

```tsx
// app/dashboard/loading.tsx
import { DashboardRouteLoading } from "@/dashboard/components/dashboard-route-loading";

export default function DashboardLoading() {
  return (
    <DashboardRouteLoading
      title="Loading dashboard"
      description="Preparing your dashboard view."
    />
  );
}
```

### UI: Component-Level Query Loading Pattern

```tsx
"use client";

import { UsersGridSkeleton } from "@/features/users/components/users-grid-skeleton";
import { useInfiniteUsers } from "@/features/users/hooks/use-infinite-users";

export function UsersGrid() {
  const { users, isLoading } = useInfiniteUsers();

  if (isLoading) {
    return <UsersGridSkeleton />;
  }

  return <div>{users.length} users loaded</div>;
}
```

### UI: Component-Level Query Error + Retry Pattern

```tsx
"use client";

import { AppErrorState } from "@/components/app-error-state";
import { useInfiniteUsers } from "@/features/users/hooks/use-infinite-users";

export function UsersGrid() {
  const { users, isLoading, error, refetch } = useInfiniteUsers();

  if (isLoading) {
    return <div>Loading users...</div>;
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load users"
        description="The users list is unavailable right now."
        onRetry={() => {
          void refetch();
        }}
        retryLabel="Retry users"
      />
    );
  }

  return <div>{users.length} users loaded</div>;
}
```

### API: Route-Service-Repository Separation

```py
# routes.py
@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user()),
    service: OrganizationService = Injected(OrganizationService),
) -> OrganizationRead:
    return service.get_organization(organization_id=organization_id, actor=current_user)

# service.py
def get_organization(self, organization_id: UUID, actor: User) -> OrganizationRead:
    organization = self.repository.find_by_id(organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    self._assert_can_view(actor, organization)
    return OrganizationRead.model_validate(organization)

# repository.py
def find_by_id(self, organization_id: UUID) -> OrganizationModel | None:
    with Session(self.delegate.engine) as session:
        return session.get(OrganizationModel, organization_id)
```

### API: Unit Test Style (given/when/then)

```py
def test_super_admin_create_organization_returns_bad_request():
    with given([...]) as context:
        client = context.client
        access_token = context.access_token

        with when("super admin tries to create an organization"):
            response = client.post(
                "/api/v1/organizations",
                json={"name": "Super Admin Org", "description": "Created by super admin"},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            with then("request is rejected with bad request"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
```

### API: Integration Test Shape

```py
def test_get_organization_requires_auth():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client = context.client

        with when("I request an organization without auth"):
            response = client.get(
                "/api/v1/organizations/11111111-1111-1111-1111-111111111111"
            )

            with then("request is rejected with unauthorized"):
                assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
```

### UI: Playwright Spec + Page Object Pattern

```ts
import { test, expect } from "@playwright/test";

import { LoginPage } from "../pages/login-page.po";
import { DataSupport } from "../pages/data-support/data-support.po";

test("user can log in", async ({ page }) => {
  const loginPage = new LoginPage(page);
  const dataSupport = new DataSupport(page);

  await dataSupport.auth.interceptLoginRequest();
  await loginPage.goto();
  await loginPage.login("user@example.com", "password123");

  await expect(page).toHaveURL(/dashboard/);
});
```

## Testing Requirements

### API

- New behavior MUST include tests for:
  - happy path,
  - permission/auth failures,
  - key validation failures,
  - not-found/conflict behaviors.
- Schema changes MUST include migration coverage and migration file.

### UI

- Changed UI behavior MUST include/update Playwright coverage where regression risk is non-trivial.
- Selectors/interactions SHOULD stay in page objects.
- Mock setup SHOULD stay in shared test support helpers.
- Assertions SHOULD stay in spec files.

## Standard Feature Workflow

### API Feature

1. Update `models.py`.
2. Add/update repository methods.
3. Add/update service logic and authorization.
4. Add/update routes.
5. Register router if needed.
6. Add migration if schema changed.
7. Add/update tests.
8. Run `make check-api` and `make test-api`.

### UI Feature

1. Add/update `schemas.ts` and inferred types.
2. Add/update query keys.
3. Add/update query/mutation hooks.
4. Build/update feature UI.
5. Wire route/page usage in `src/app`.
6. Add/update Playwright coverage.
7. Run `make lint-ui`, `pnpm -s tsc --noEmit`, and relevant tests.

## Versioning and Releases

Each deployable is its own Helm chart with two independent versions in `Chart.yaml`:

- `appVersion` — the container image tag the deploy builds and pushes. Bump it whenever that service's image content (code) changes: minor for features, patch for fixes.
- chart `version` — the chart packaging version. Bump it when that chart's templates/values change, independently of app code.

Rules:

- Frontend and backend versions are independent and will drift apart. Do not keep them in lockstep — bump only the service(s) that actually changed.
- `appVersion` tags are immutable: never reuse an `appVersion` for different code. The deploy would overwrite the tag, and pods would not roll.
- Bump versions late — ideally the last commit before opening the PR — so you bump off the freshest `main` and avoid version-line merge conflicts.
- The product/release identifier is the git commit/PR, not a shared chart number.
- `deploy.yml` derives the API and UI image tags from `appVersion` in `helm/agentfarm-api/Chart.yaml` and `helm/agentfarm-ui/Chart.yaml`. `litellm` and `postgres` have no `appVersion` (they run upstream images); bump only their chart `version` when their templates change.

## Review Guidance

When asked to review code, prioritize in this order:

1. Correctness and regressions.
2. Data contract and schema safety.
3. Query key and invalidation correctness.
4. Auth and permission behavior.
5. Loading and async UX behavior.
6. Test coverage gaps.

Do not lead with style-only feedback unless it impacts correctness or maintainability.

## Definition of Done

- Behavior covers happy path and key edge cases.
- Validation and authorization are correct.
- Tests for changed behavior are added/updated and passing.
- Lint/type/check commands pass for touched areas.
- Migrations are included for DB schema changes.
- Helm `appVersion`/chart `version` are bumped for changed service images/charts.
- No unrelated refactors or style churn.
