# Web app guidelines

## Project-defining frontend rules

- Feature logic lives under `ui/src/features/<feature>/`.
- Normal application API calls use `ui/src/shared/api`.
- Important API responses are validated with feature-local Zod schemas.
- Query keys use centralized helpers rather than scattered literal arrays.
- Server Components are the App Router default; add `"use client"` only for client-owned behavior.
- Select loading and error boundaries according to who owns the asynchronous work.

Read `docs/architecture/ui.md` before changing authentication, organization scoping, provider composition, query-cache isolation, or SSE behavior.

## Feature structure

Use this baseline when the feature earns each part:

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

Optional additions include `providers/`, `stores/`, `constants.ts`, and a small barrel export. Route composition remains under `ui/src/app/`.

## Schemas and API boundaries

- Export a Zod schema and its inferred type from the same feature-local file.
- Avoid handwritten interfaces that duplicate schema-inferred API types.
- Use the shared client's existing snake_case/camelCase transformations.
- Do not introduce ad hoc fetch wrappers or Axios instances for ordinary app API calls.
- Supply a Zod schema to the API client for important responses.
- Keep the SSE log proxy as an explicit streaming exception; do not generalize it into the normal request pattern.

## Queries and mutations

- Define keys through `ui/src/shared/query-keys.ts` patterns and feature-local helpers.
- Add `enabled` guards when required IDs or context may be absent.
- Prefer `useInfiniteQuery` for progressive load-more behavior.
- Mutations MUST invalidate affected list and detail families.
- Hooks SHOULD return domain-oriented fields such as `agent`, `isLoadingAgent`, and `error` rather than leaking raw query objects unnecessarily.
- Determine whether new queries are organization-scoped. Include organization identity in the key or update the organization-switch isolation behavior described in `docs/architecture/ui.md`.

## Loading and errors

- Use route-segment `loading.tsx` for router-owned, page-blocking waits.
- Use route-segment `error.tsx` when the page cannot render meaningfully after an initial page-blocking failure.
- Use local skeletons or loading states for component-owned initial work.
- Keep follow-up search, pagination, and refetch loading local after the page has rendered.
- Render inline errors with retry for component-owned failures.
- Distinguish authentication or permission failures when `ApiError` exposes that information.
- Use local `Suspense` boundaries for subtree waits.
- Reserve provider fallbacks for provider-owned hydration or context waits.

## React and state

- Avoid `useEffect` for derived render data.
- Put user-triggered workflows in handlers or mutation callbacks rather than effect chains.
- Keep server data in TanStack Query and client-only state in the appropriate local/provider/Zustand boundary.
- Preserve provider ordering and organization-header timing when changing protected route composition.

## Imports and naming

- Use `kebab-case` filenames.
- Use `PascalCase` for components and `use...` names for hooks.
- Order imports as external packages, `@/*` aliases, then relative imports.
- Prefer `@/*` aliases for internal imports.
- Reuse existing UI primitives before introducing new ones.

## UI feature workflow

1. Add or update Zod schemas and inferred types.
2. Add or update centralized query keys.
3. Add query and mutation hooks through the shared API client.
4. Build feature components.
5. Compose them from `ui/src/app/` routes.
6. Add or update Playwright coverage following `docs/guidelines/testing.md`.
7. Run the UI checks listed in `docs/guidelines/testing.md`.
8. Apply UI versioning rules from `docs/guidelines/operations.md` when release preparation is requested.

## Maintaining conventions

When a repeatable frontend convention changes, update this file once rather than copying the rule into feature docs. Feature docs under `docs/features/` own product invariants and boundaries, not generic React or query guidance.
