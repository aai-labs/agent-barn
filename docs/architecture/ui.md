# UI Architecture

## Read when

Read before changing App Router structure, authentication or organization providers, API calls, query keys, loading/error behavior, or Playwright coverage.

## Provider and routing boundaries

The root layout composes `NuqsAdapter`, `QueryProvider`, `TooltipProvider`, and `AppProvider`. `AppProvider` lets public auth routes bypass protected context; other routes resolve the current user and organization before protected children render.

App Router pages are composition points. Feature behavior belongs under `../../ui/src/features/`; authentication behavior belongs in `../../ui/src/auth/`; shared transport and query infrastructure belongs in `../../ui/src/shared/`.

The active organization comes from `/dashboard/[orgId]`. Platform View lives under `/dashboard/platform` and has no active Organization. `OrganizationProvider` keeps remembered organization state only so `/dashboard` and the switcher can return to Organization View; org-scoped API hooks build `/api/v1/organizations/{organization_id}/...` URLs instead of mutating shared request headers. Inaccessible organization URLs redirect to an available fallback.

## API and query invariants

- Normal application HTTP calls use the singleton exported from `../../ui/src/shared/api`.
- The client sends cookies, transforms request keys to snake_case and response keys to camelCase, and surfaces `ApiError`. Request keys that contain `-`, or that are already UPPER_SNAKE (`/^[A-Z0-9_]+$/`, such as enum codes used as map keys), are sent unchanged.
- Important responses are validated with feature-local Zod schemas supplied by hooks.
- Query keys use the centralized factory in `../../ui/src/shared/query-keys.ts` and feature-local key helpers.
- Several organization-scoped keys do not include organization ID. `OrganizationProvider` removes the known organization-scoped query families on a genuine organization switch to prevent prior-organization data from remaining visible.
- Adding an organization-scoped query family requires updating that eviction set or changing the key design so organization identity is represented safely.

Streaming is an explicit exception to the normal client flow. The agent log stream uses a Next route handler and `../../ui/src/features/agents/hooks/use-agent-log-stream.ts`; Dashboard Web Chat connects to its authenticated organization-scoped SSE route through `../../ui/src/features/agents/hooks/use-web-chat.ts`. Each hook owns abort and bounded reconnection behavior. The shared API auth interceptor supplies and refreshes the bearer token before each raw streaming fetch and is forced after a 401, so the streaming exception does not bypass session recovery. Web Chat history is capped at the newest 500 messages and returned chronologically; the live stream advances by message ID and uses delivery-scoped reads for status signals, while frames upsert by message ID so delivery-status, `cancel_requested_at`, approval, or `error_message` changes update an existing message rather than creating duplicates. A command-approval prompt is converted to an assistant-ui `data` part named `approval`; `web-chat-approval.tsx` registers its renderer only for users whose Agent `allowed_actions` include `agent.update`, so a viewer sees the prompt text without buttons, and a click sends the choice with its `approval_id` and disables that approval's buttons unless the send fails. The additive `error_message` field carries the already-redacted terminal delivery summary; the UI tolerates its absence while an older API replica is still serving history. A processing message with `cancel_requested_at` is no longer treated as awaiting a reply while the runtime finishes its soft cancellation.

## Dashboard navigation

`../../ui/src/app/dashboard/layout.tsx` wraps every dashboard page in `NavVariantProvider` and `AppShell` from `../../ui/src/features/navigation/`. The shell renders one of four navigation layouts, chosen per browser while the team evaluates them:

- `current` (the default): the top bar in `../../ui/src/components/top-nav.tsx`.
- `c`: one light sidebar that drills in. On Organization pages it holds the Organization switcher, the Organization's pages and its Agents; opening an Agent, its settings, Organization settings or Platform View replaces its contents with that context's sections and a way back. On phones it opens as a drawer from the top bar.
- `d`: a dark rail of Organization destinations, plus a light panel listing the sections of whatever the page belongs to (an Agent, its settings, Organization settings, Platform View).
- `d2`: `d`, except that Platform View gets its own indigo rail of areas (Overview, Users, Organizations, Spend, Catalog, System); an area with more than one page gets a panel styled like every other panel. On desktop a path bar runs along the top (`path-bar.tsx`): the Organization or Platform switcher, then the current Agent with a switcher that keeps the section you are on, then the current page; inside an Agent it also carries the update notice, the lifecycle menu and Share, and the account menu ends it. The rail therefore has no switcher, account menu or Platform entry of its own. On desktop the Agent page drops its own header and section titles, the Overview card carries the Agent's avatar beside its blueprint, and Chat and Conversations fill the page and the panel shows their thread or channel list, with a way back to the Agent's sections; the selected thread and channel stay in the URL (`?thread=`, `?channel=`) so the list and the page stay in step.

The choice lives in localStorage; `?nav=current|c|d|d2` on any dashboard URL sets it, and every layout's account menu offers it. Outside `current`, an Agent opens on its Overview (the About section, listed first) and Chat moves to `?tab=chat`; navigation lists each page's sections, so pages read `sectionsInNav` from `useNavVariant()` and leave out the Agent page's tab row and the sidebars of Agent configuration and the settings pages (`SettingsPageLayout`). In `d`/`d2` on phones the rail becomes a bottom bar and the panel a section sheet opened from the top bar. Section lists that navigation and its page both show come from one helper (`visibleAgentPageTabs`, `visibleAgentConfigurationSections`, `visibleOrganizationSettingsSections`, `PLATFORM_SETTINGS_SECTIONS`) so their Permission gates cannot drift. Navigation reads the current Agent from the query cache rather than fetching it, because it also renders where no Organization is active.

## Loading and errors

Dashboard navigation has route-level `../../ui/src/app/dashboard/loading.tsx` and `../../ui/src/app/dashboard/error.tsx` boundaries. Client-owned query loading and follow-up failures remain inside feature components with inline retry UI. A hook error does not automatically reach an App Router error boundary.

## Testing

Playwright specs live in `../../ui/tests/e2e/`. Selectors and interactions belong in page objects under `../../ui/tests/pages/`; domain request interception and fixtures belong in shared data-support helpers. Assertions stay in specs.

Use `make lint-ui`, `make check-ui`, and relevant Playwright tests for changed behavior.

## Source map

| Concern                                    | Source                                                                                                            |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Dashboard navigation shell and preview     | `../../ui/src/features/navigation/`, `../../ui/src/components/top-nav.tsx`                                              |
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

## Personal API Key settings

The account feature manages User-owned keys through the shared API client. The complete key appears only in local component state after creation; list responses return safe metadata. Key-list queries are account-scoped and refresh after creation or revocation. The root `llms.txt` routes forward public developer content from the Product API.
