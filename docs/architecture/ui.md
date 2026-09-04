# UI Architecture

## Read when

Read before changing App Router structure, authentication or organization providers, API calls, query keys, loading/error behavior, or Playwright coverage.

## Provider and routing boundaries

The root layout composes `NuqsAdapter`, `QueryProvider`, `TooltipProvider`, and `AppProvider`. `AppProvider` lets public auth routes bypass protected context; other routes resolve the current user and organization before protected children render.

App Router pages are composition points. Feature behavior belongs under `../../ui/src/features/`; authentication behavior belongs in `../../ui/src/auth/`; shared transport and query infrastructure belongs in `../../ui/src/shared/`.

The active organization comes from `/dashboard/[orgId]`. Platform View lives under `/dashboard/platform` and has no active Organization. `OrganizationProvider` keeps remembered organization state only so `/dashboard` and the switcher can return to Organization View; org-scoped API hooks build `/api/v1/organizations/{organization_id}/...` URLs instead of mutating shared request headers. Inaccessible organization URLs redirect to an available fallback.

## API and query invariants

- Normal application HTTP calls use the singleton exported from `../../ui/src/shared/api`.
- The client sends cookies, transforms request keys to snake_case and response keys to camelCase, and surfaces `ApiError`.
- Important responses are validated with feature-local Zod schemas supplied by hooks.
- Query keys use the centralized factory in `../../ui/src/shared/query-keys.ts` and feature-local key helpers.
- Several organization-scoped keys do not include organization ID. `OrganizationProvider` removes the known organization-scoped query families on a genuine organization switch to prevent prior-organization data from remaining visible.
- Adding an organization-scoped query family requires updating that eviction set or changing the key design so organization identity is represented safely.

Streaming is an explicit exception to the normal client flow. The agent log stream uses a Next route handler and `../../ui/src/features/agents/hooks/use-agent-log-stream.ts`; Dashboard Web Chat connects to its authenticated organization-scoped SSE route through `../../ui/src/features/agents/hooks/use-web-chat.ts`. Each hook owns abort and bounded reconnection behavior. The shared API auth interceptor supplies and refreshes the bearer token before each raw streaming fetch and is forced after a 401, so the streaming exception does not bypass session recovery. Web Chat history is capped at the newest 500 messages and returned chronologically; the live stream advances by message ID and uses delivery-scoped reads for status signals, while frames upsert by message ID so delivery-status or `cancel_requested_at` changes update an existing inbound message rather than creating duplicates. A processing message with `cancel_requested_at` is no longer treated as awaiting a reply while the runtime finishes its soft cancellation.

## Loading and errors

Dashboard navigation has route-level `../../ui/src/app/dashboard/loading.tsx` and `../../ui/src/app/dashboard/error.tsx` boundaries. Client-owned query loading and follow-up failures remain inside feature components with inline retry UI. A hook error does not automatically reach an App Router error boundary.

## Testing

Playwright specs live in `../../ui/tests/e2e/`. Selectors and interactions belong in page objects under `../../ui/tests/pages/`; domain request interception and fixtures belong in shared data-support helpers. Assertions stay in specs.

Use `make lint-ui`, `make check-ui`, and relevant Playwright tests for changed behavior.

## Source map

| Concern                                    | Source                                                                                                            |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Root providers                             | `../../ui/src/app/layout.tsx`, `../../ui/src/shared/providers/app-provider.tsx`                                               |
| Current-user gate                          | `../../ui/src/auth/providers/user-context-provider.tsx`                                                                 |
| Organization selection and cache isolation | `../../ui/src/features/organizations/providers/organization-provider.tsx`                                               |
| API client and interceptors                | `../../ui/src/shared/api/`                                                                                              |
| Query-key factory                          | `../../ui/src/shared/query-keys.ts`                                                                                     |
| Route boundaries                           | `../../ui/src/app/error.tsx`, `../../ui/src/app/dashboard/loading.tsx`, `../../ui/src/app/dashboard/error.tsx`                      |
| SSE proxy and client                       | `../../ui/src/app/api/v1/organizations/[organizationId]/agents/[agentId]/logs/stream/route.ts`, `../../ui/src/features/agents/hooks/use-agent-log-stream.ts` |
| Playwright configuration and support       | `../../ui/playwright.config.ts`, `../../ui/tests/`                                                                            |

## Change impact

When adding a feature query, define its schema and centralized key, decide whether it is organization-scoped, and verify switch behavior. When changing page-blocking data, align route loading/error boundaries with component-owned retry behavior. When changing API contracts, update the corresponding Zod schemas, hooks, mocks, and Playwright expectations.
