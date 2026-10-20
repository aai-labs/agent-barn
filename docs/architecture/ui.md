# UI Architecture

## Read when

Read before changing App Router structure, authentication or organization providers, API calls, query keys, loading/error behavior, or Playwright coverage.

## Provider and routing boundaries

The root layout composes `NuqsAdapter`, `QueryProvider`, `TooltipProvider`, and `AppProvider`. `AppProvider` lets public auth routes bypass protected context; other routes resolve the current user and organization before protected children render.

App Router pages are composition points. Feature behavior belongs under `../../ui/src/features/`; authentication behavior belongs in `../../ui/src/auth/`; shared transport and query infrastructure belongs in `../../ui/src/shared/`.

The active organization comes from `/dashboard/[orgId]`. Platform View lives under `/dashboard/platform` and has no active Organization. `OrganizationProvider` keeps remembered organization state only so `/dashboard` and the switcher can return to Organization View; org-scoped API hooks build `/api/v1/organizations/{organization_id}/...` URLs instead of mutating shared request headers. Inaccessible organization URLs redirect to an available fallback.

The welcome, password and onboarding pages compose the shared `SplitFrame` from
`ui/src/components/split-frame.tsx`. Agent creation in onboarding reuses
`use-hire-agent-form.ts` with the dashboard hire dialog. Telegram QR codes are rendered
locally with `qrcode.react`; link tokens are not sent to an external QR service.
See [Trial onboarding](../features/trial-onboarding.md#flow) for the user flow.

## API and query invariants

- Normal application HTTP calls use the singleton exported from `../../ui/src/shared/api`.
- The client sends cookies, transforms request keys to snake_case and response keys to camelCase, and surfaces `ApiError`. Request keys that contain `-`, or that are already UPPER_SNAKE (`/^[A-Z0-9_]+$/`, such as enum codes used as map keys), are sent unchanged.
- Important responses are validated with feature-local Zod schemas supplied by hooks.
- Query keys use the centralized factory in `../../ui/src/shared/query-keys.ts` and feature-local key helpers.
- Several organization-scoped keys do not include organization ID. `OrganizationProvider` removes the known organization-scoped query families on a genuine organization switch to prevent prior-organization data from remaining visible.
- Adding an organization-scoped query family requires updating that eviction set or changing the key design so organization identity is represented safely.

Streaming is an explicit exception to the normal client flow. The agent log stream uses a Next route handler and `../../ui/src/features/agents/hooks/use-agent-log-stream.ts`; Dashboard Web Chat connects to its authenticated organization-scoped SSE route through `../../ui/src/features/agents/hooks/use-web-chat.ts`. Each hook owns abort and bounded reconnection behavior. The shared API auth interceptor supplies and refreshes the bearer token before each raw streaming fetch and is forced after a 401, so the streaming exception does not bypass session recovery. Web Chat history is capped at the newest 500 messages and returned chronologically; the live stream advances by message ID and uses delivery-scoped reads for status signals, while frames upsert by message ID so delivery-status, `cancel_requested_at`, approval, or `error_message` changes update an existing message rather than creating duplicates. A command-approval prompt is converted to an assistant-ui `data` part named `approval`; `web-chat-approval.tsx` registers its renderer only for users whose Agent `allowed_actions` include `agent.update`, so a viewer sees the prompt text without buttons, and a click sends the choice with its `approval_id` and disables that approval's buttons unless the send fails. The additive `error_message` field carries the already-redacted terminal delivery summary; the UI tolerates its absence while an older API replica is still serving history. A processing message with `cancel_requested_at` is no longer treated as awaiting a reply while the runtime finishes its soft cancellation.

## Dashboard navigation

`../../ui/src/app/dashboard/layout.tsx` wraps every dashboard page in `AppShell` from `../../ui/src/features/navigation/`.

- **Rail** (`nav-rail.tsx`): a dark column on the left listing the Organization's pages (Team, Usage, Costs, KPIs, Members, Settings; Costs, KPIs and Members only for those who manage the Organization). In Platform View it turns indigo and lists Platform's own areas (Overview, Users, Organizations, Spend, Catalog, System).
- **Path bar** (`path-bar.tsx`): along the top. Its first step switches Organization or enters Platform View (the only way in); inside an Agent the next step is the Agent, with a switcher that keeps the section you are on; the last step names the page. Inside an Agent it also carries a chip with the Agent's status, runtime and model, the update notice, the lifecycle menu and Share. The account menu ends it.
  - Switching Agent carries only the parameters that name a place in the page (`tab`, `section`, `range`), never one Agent's thread or channel. The switcher's list is fetched when it first opens.
  - Switching Organization keeps the page you are on, except a page about one of the old Organization's things: an Agent and its sub-pages land on the new Organization's team, a skill or template on that settings tab (`organizationSwitchTarget`).
- **Panel** (`context-panel.tsx`): the sections of whatever the page belongs to — an Agent, its settings, Organization settings, or a Platform area with more than one page — and nothing on pages without sections. Pages therefore have no tab rows or section sidebars of their own (`SettingsPageLayout` renders one section).
- **Phones**: the rail becomes a bottom bar with More for the rest, the Organization switch, creating an Organization and the account; the panel becomes a sheet opened from the top bar.
- **Desktop or phone**: the shell switches by CSS at the `lg` breakpoint, so the first paint is already the right layout. Only controls that would otherwise exist twice wait for the width check (`useIsDesktop`): the Agent's lifecycle menu and Share, which the path bar carries on desktop and the Agent page on phones.

An Agent opens on its Overview (the About section, listed first; Chat is `?tab=chat`). On desktop the Agent page has no header of its own (the path bar names the Agent), the Overview card carries the Agent's avatar beside its blueprint, and Chat and Conversations fill the page (`.af-page-fill`) while the panel shows their thread or channel list with a way back to the sections; the selected thread and channel stay in the URL (`?thread=`, `?channel=`). The fill is CSS too, so an open conversation and its draft survive the window crossing the breakpoint. The Agent's notices (`AgentNotices`: pending model, update outcome, failure, messaging setup) show above every section, full-page ones included. Hiring starts from the Your team page.

Section lists that navigation and its page both show come from one helper (`visibleAgentPageTabs`, `visibleAgentConfigurationSections`, `visibleOrganizationSettingsSections`, `PLATFORM_SETTINGS_SECTIONS`) so their Permission gates cannot drift. Navigation reads the current Agent from the query cache rather than fetching it, because it also renders where no Organization is active.

## Loading and errors

Dashboard navigation has route-level `../../ui/src/app/dashboard/loading.tsx` and `../../ui/src/app/dashboard/error.tsx` boundaries. Client-owned query loading and follow-up failures remain inside feature components with inline retry UI. A hook error does not automatically reach an App Router error boundary.

## Testing

Playwright specs live in `../../ui/tests/e2e/`. Selectors and interactions belong in page objects under `../../ui/tests/pages/`; domain request interception and fixtures belong in shared data-support helpers. Assertions stay in specs.

Use `make lint-ui`, `make check-ui`, and relevant Playwright tests for changed behavior.

## Source map

| Concern                                    | Source                                                                                                            |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Dashboard navigation shell                 | `../../ui/src/features/navigation/`                                                                                     |
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
