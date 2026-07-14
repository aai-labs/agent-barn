# AF-167: Add Audit Logging — Implementation Plan

Ticket: https://aai-labs.atlassian.net/browse/AF-167
Branch: `AF-167-add-audit-logging`

## Context

The control plane has no record of who did what. This ticket adds audit logging that captures **user actions** across the app — the acting user, the action, the target, the timestamp, and (for updates) which fields changed. This is distinct from the agent conversation/tool-call ingest of Epic AF-5, which records what *agents* do; here we record what *humans* do in the UI/API.

Acceptance criteria:

- Almost every user action is captured — mutations (create/start/stop/update/delete agents, credential changes, role/org/member changes, template changes, …) **and** significant reads (opening an agent's details page, viewing conversations, viewing tool calls).
- Every entry records actor, action, target, timestamp; updates record which field(s) changed.
- The action set can grow over time — err toward capturing more.
- Org admins can view their own org's audit log; superusers can view every org's.
- The log can be filtered and exported.

## Decisions (confirmed with Samuel)

| Decision | Choice |
|---|---|
| UI placement | **New** `/dashboard/[orgId]/audit-log` page + `/dashboard/audit-logs` superuser page. The mock `/activity` page stays untouched (it's AF-5's agent-activity feed, a different concept). |
| Auth events | **Included** (login, failed login, logout, password flows). They carry `organization_id = NULL`, so they appear only in the superuser view in v1. |
| CI guard | **Yes** — a unit test walks every API route and fails if it's neither in the audited-routes map nor in an explicit exempt list with a reason. |
| Delivery | **Single PR** on this branch (backend + frontend). |
| Capture mechanism | **Explicit `AuditLogService.record(...)` calls** (service layer for mutations, route layer for reads). Middleware rejected: it resolves before the auth dependency (no `CurrentUserContext`), can't see changed fields or target labels, and would still need a hand-maintained route→action map. |
| Pagination | Offset (`Pagination`/`PaginatedItems`), ordered `created_at desc, id desc`. Matches every other list endpoint and gives totals; uuid7 ids keep a keyset-cursor upgrade path open. |
| Export | CSV via `StreamingResponse`, keyset-batched internally, 100k-row hard cap. |

## Verified codebase anchors

- Backend is DDD: `api/domains/<domain>/{models,repository,service,routes}.py`, SQLModel over **sync** SQLAlchemy, `injector` DI (`@inject @singleton @dataclass`), routers mounted on a subapp at `/api/v1` in `api/api_app.py`.
- `get_current_user(...)` factory (`api/domains/auth/utils.py:123`) yields `CurrentUserContext` (`api/domains/auth/models.py:102`): `.user` (id, email, full_name, is_superuser), membership map, `require_org_role` / `require_superuser` / `require_current_user_organization`.
- Roles: `ORG_MANAGER_ROLES = {OWNER, ADMIN}` (`api/domains/users/organization_users/models.py`); superuser transcends orgs.
- `BaseModel(SQLModel)` (`api/infrastructure/postgres/models.py`) provides uuid7 `id` + tz-aware `created_at`/`updated_at` — `created_at` doubles as the event timestamp.
- `PostgresRepositoryDelegate` (`api/infrastructure/postgres/repository.py`): singleton engine; **`save()` opens a session and commits per call** (line 234), so "record after the repo save returns" genuinely means "after commit". Generic `find_all_paginated_by_query(model, query, pagination, order_by)` handles count+offset+order.
- Update endpoints already produce the changed-field set via `model_dump(exclude_unset=True)` (e.g. `organizations/service.py:149`, `agents/service.py:619`).
- JSONB column precedent: `api/domains/tool_calls/models.py:40` (`SqlField(sa_column=Column(JSONB, ...))`).
- Filter pattern: `*Filter` Pydantic model + `get_*_filter` Query dependency (`organizations/models.py:63-70`, `tool_calls/models.py:77-95`).
- Role-gated route precedent: `costs/routes.py` (`Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES))`, `start_date`/`end_date` as plain query strings).
- Alembic: `api/migrations/`; **new model modules must be imported in `migrations/env.py`**; `make makemigrations` / `make migrate`.
- Tests: pytest + testcontainers Postgres (`api/tests/conftest.py`), `tests/{unit,integration,steps,mocks,core}`; mock injector modules in `tests/core/modules.py`; cross-org example `tests/integration/test_cross_org_isolation.py`.
- No existing middleware (CORS only), no exception handlers, no audit tables, no CSV export anywhere.
- Frontend: Next.js App Router in `ui/`. Axios wrapper `api` (`ui/src/shared/api/api-instance.ts`) auto-attaches Bearer + `X-Organization-Id`; **`api.getFile(url)` returns a Blob** (for CSV download). `humps` converts snake↔camel on bodies/responses (query strings stay snake_case, built manually). Role gating: `useActiveOrgRole()` → `{ role, canManage }`, `SuperAdminOnly`, `useRequireOrgManager()`. Best table pattern: `ui/src/features/costs/components/costs-dashboard.tsx` (af-card table, native date inputs with draft/apply, expandable rows via `Set<string>`, Prev/Next). Nav: `ui/src/components/top-nav.tsx` (`navTabs` ~line 31, superuser menu ~line 154). No shadcn select/date-picker/table — native `<select className="af-select">`, `<input type="date">`, hand-rolled tables.

---

## 1. Data model — new domain `api/domains/audit_logs/`

### `api/domains/audit_logs/models.py`

```python
class AuditLog(BaseModel, table=True):        # inherits uuid7 id, created_at (= event timestamp)
    __tablename__: str = "audit_log"

    organization_id: uuid.UUID | None = Field(default=None, nullable=True)  # NULL = global (auth.*, user.*)
    actor_user_id: uuid.UUID | None = Field(default=None, nullable=True)    # NULL for login_failed w/ unknown email
    actor_email: str | None = Field(default=None, nullable=True)            # snapshot — survives user deletion
    actor_name: str | None = Field(default=None, nullable=True)
    is_superuser_actor: bool = Field(default=False, nullable=False)
    action: str = Field(nullable=False, max_length=100)                     # "agent.create" — varchar, NOT a PG enum
    target_type: str | None = Field(default=None, nullable=True)
    target_id: uuid.UUID | None = Field(default=None, nullable=True)
    target_label: str | None = Field(default=None, nullable=True)           # human-readable snapshot
    changed_fields: dict | None = SqlField(default=None, sa_column=Column(JSONB, nullable=True))

    __table_args__ = (
        sa.Index("ix_audit_log_org_created", "organization_id", "created_at"),
        sa.Index("ix_audit_log_created", "created_at"),        # superuser all-orgs view
        sa.Index("ix_audit_log_actor", "actor_user_id"),
        sa.Index("ix_audit_log_action", "action"),
        sa.Index("ix_audit_log_target", "target_type", "target_id"),
    )
```

Design points:

- **No FK constraints** on `actor_user_id`/`organization_id`. The log is a historical record: an FK would either cascade-delete history when a user/org is deleted or SET NULL and lose the association. Plain UUIDs + the email/name snapshots keep rows intact and readable after deletion. The superuser view left-joins `organization` for the current org name and falls back to the raw UUID for deleted orgs.
- **`action` is a plain varchar** backed by a Python `AuditAction(StrEnum)` in the same module. A PG enum would require a migration per new action (`alembic_postgresql_enum` is installed and autogenerates enum diffs) — the ticket explicitly wants the action set to grow freely. `record()` accepts `AuditAction | str` so a one-off action never blocks logging.
- **`changed_fields` format** (updates only): `{"<field>": {"old": ..., "new": ...}}` for **value-allowlisted** fields, `{"<field>": "[redacted]"}` for everything else. **Default-deny**: values are stored only for fields on an explicit per-target allowlist (`name`, `description`, `model`, `approval_mode`, `role`, `template_slug`, `template_version`, `skill_ids`, `slack_channels`, …). Token/secret/password fields (`slack_bot_token`, `slack_app_token`, `teams_app_password`, `secrets[]`, `access_token`, `refresh_token`, any future field) are name-only *by construction* — only an explicit allowlist addition (code-reviewable) can ever expose a value. Auth flows always pass `changed_fields=None`.
- `TargetType` string constants: `agent`, `organization`, `member`, `user`, `template`, `skill`, `integration`, `audit_log`.

Also in `models.py`:

- `AuditAction(StrEnum)` — full initial set in §3.
- `AuditLogRead` (Pydantic, `from_attributes=True`): all row fields + `organization_name: str | None` (populated by the read query's join, for the superuser view).
- `AuditLogFilter` + `get_audit_log_filter(...)` Query dependency, mirroring `get_organization_filter` / `get_tool_call_filter`:
  - `actor_user_id: UUID | None`
  - `search: str | None` — ilike over `actor_email` / `target_label`
  - `action: str | None`
  - `target_type: str | None`, `target_id: UUID | None`
  - `start_date: str | None`, `end_date: str | None` (ISO dates, same style as costs)
  - `organization_id: UUID | None`, `scope: Literal["org","all"] = "org"` — **honored only for superusers** (see §4)

### Migration

- Add `import api.domains.audit_logs.models  # noqa: F401` to `api/migrations/env.py`.
- `make makemigrations` → verify the revision creates `audit_log` with the JSONB column and all 5 indexes → `make migrate`.
- No seed/bootstrap changes (the `api_app.py` lifespan bootstrap is not a user action and is not logged).

## 2. Capture mechanism

### `api/domains/audit_logs/service.py` — `AuditLogService`

`@inject @singleton @dataclass`, receives `AuditLogRepository` (which wraps the delegate, standard pattern).

```python
def record(
    self, *,
    action: AuditAction | str,
    context: CurrentUserContext | None = None,
    actor_user_id: UUID | None = None,      # override/fallback when no context (login_failed)
    actor_email: str | None = None,
    organization_id: UUID | None | _Unset = UNSET,  # default: context.current_user_organization.organization_id
    target_type: str | None = None,
    target_id: UUID | None = None,
    target_label: str | None = None,
    changed_fields: dict | None = None,
) -> None: ...
```

Semantics:

- **Never raises.** The whole body is wrapped in `try/except Exception: logger.exception(...)`. An audit write failure must never fail the user's request.
- **Success-only by placement**: called as the *last* statement of a service method, after the repository `save()` returned — and since `delegate.save()` commits per call, that is genuinely post-commit. Sync write on the request's threadpool thread; no async offload needed.
- Actor snapshot from `context.user` (`id`, `email`, `full_name`, `is_superuser`). Explicit `actor_*` kwargs cover the no-context cases (failed login, logout token decode).
- `organization_id` defaults to the context's current org; pass `organization_id=None` explicitly for global events (`auth.*`, superuser `user.*` admin).
- **Read-noise suppression**: for actions in a `READ_ACTIONS` frozenset, an in-memory `dict[(actor_id, action, target_id), monotonic_ts]` guarded by `threading.Lock` (the service is a singleton; routes run in threadpool threads) suppresses duplicate entries within a **5-minute window** — absorbs React Query refetch-on-focus without losing the "user opened agent X" signal. Mutations always write.

Helpers in the same module:

- `redact_changed_fields(changed: dict, value_allowlist: set[str]) -> dict` — default-deny value filter.
- `diff_changed_fields(before, update_payload_exclude_unset: dict, value_allowlist) -> dict` — builds `{field: {"old": ..., "new": ...}}` from the pre-update model + the `exclude_unset` dict (values only for allowlisted fields).

Plus `list_logs(context, filters, pagination) -> PaginatedItems[AuditLogRead]` and `iter_export_rows(context, filters) -> Iterator[str]` (§4–5).

### Placement rule (prevents double logging)

**Mutations are recorded inside service methods; reads are recorded inside route handlers.** Reads must not live in services because services reuse getters internally — e.g. `tool_calls/routes.py` calls `agent_service.get_agent(...)` as a scoping check, which would otherwise emit a spurious `agent.view` for every tool-call listing. Routes inject the service with `Injected(AuditLogService)` exactly like any other service.

### CI route-coverage guard

- `api/domains/audit_logs/registry.py`:
  - `AUDITED_ROUTES: dict[str, AuditAction | tuple[AuditAction, ...]]` — route endpoint-function name → action(s), e.g. `"create_agent": AuditAction.AGENT_CREATE`.
  - `AUDIT_EXEMPT_ROUTES: dict[str, str]` — name → reason, e.g. `"health_v1": "infra probe"`, `"refresh_access_token": "token refresh, not a user action"`.
  - Doubles as living documentation of the entire audit surface.
- `api/tests/unit/test_audit_route_coverage.py` — builds the app via `create_app()` (mock injector modules from `tests/core/modules.py`), walks the mounted subapp's `APIRoute`s, and **fails if any route name appears in neither map**. Adding an endpoint without deciding its audit story breaks CI — this is how "err toward capturing more" survives future development.

## 3. Initial action set (concrete call sites)

### Mutations (recorded in services, after commit)

| Action | Call site | Target / changed_fields notes |
|---|---|---|
| `agent.create` | `AgentService.create_agent` (`agents/service.py:410`) | target = agent id, label = name. No payload values (create payload contains tokens). |
| `agent.update` | `AgentService.update_agent` (`agents/service.py:619`) | `diff_changed_fields` over `data.model_dump(exclude_unset=True)`; value allowlist `{name, model, approval_mode, template_slug, template_version, skill_ids, removed_skill_ids, slack_channels}`; token/secret fields name-only. |
| `agent.start` / `agent.stop` / `agent.delete` | `start_agent:827`, `stop_agent:1230`, `delete_agent:1256` | agent id + name label. |
| `agent.pair` | `pair_agent:1280` | |
| `agent.integration_validate` | `validate_integration:1443` | provider as `target_label` — it exercises stored credentials, worth logging. |
| `org.create` / `org.update` / `org.delete` | `OrganizationService.create/update/delete_organization` (`organizations/service.py:56/149/175`); create records after the multi-step `session.commit()` at `:82` | update: name/description old→new. |
| `member.add` / `member.role_change` / `member.remove` / `member.ownership_transfer` / `member.invite_resend` | `users/organization_users/service.py:186/231/264/296/318` | target = member user id, label = member email; role_change records `{"role": {"old","new"}}`. |
| `template.create` / `template.update` | `templates/service.py:140/178` | slug as label; update diffs allowlisted fields. |
| `skill.create` / `skill.update` / `skill.delete` | `skills/service.py:122/136/160` | |
| `user.create` / `user.password_reset` / `user.delete` | `users/service.py` methods behind `users/routes.py:38/50/61` (superuser admin) | `organization_id=None` (global). `delete_user` already takes `actor_id` — extend to context or record from route. |
| `auth.login` / `auth.login_failed` | `auth/routes.py:51` (inline logic → record in the route) | success after token pair; failure in both credential-exception branches with `actor_email=form_data.username`, `actor_user_id` when the user exists. **Highest-value security signal in the ticket.** `organization_id=None`. |
| `auth.logout` | `auth/routes.py:193` | route has no auth dependency — best-effort decode via `OAuth2PasswordBearer(auto_error=False)`; skip silently when absent. |
| `auth.password_change` / `auth.password_reset_request` / `auth.password_reset` / `auth.set_password` / `auth.profile_update` | `auth/routes.py:141/158/175/184/132` (reset/set: record inside `AuthService.reset_password`/`accept_invite` where the user resolves from the token) | never any field values. |
| `auth.slack_config_token_save` / `auth.slack_config_token_delete` | `auth/routes.py:213/224` | name-only; values never logged. |
| `integration.google_connect` | `google_token_exchange` (`integrations/google_oauth/routes.py:218`) | `authorize-url`/`callback` exempt (no durable state / no user token on callback). |

### Significant reads (recorded in routes; suppression window applies)

| Action | Route |
|---|---|
| `agent.view` | `get_agent` (`agents/routes.py:104`) — the agent detail page fetch |
| `agent.logs_view` | `get_agent_logs` + `get_agent_log_history` (`agents/routes.py:83/94`); `stream_agent_logs` exempt (SSE) |
| `agent.conversations_view` | `list_channels` + `list_channel_messages` (`conversations/routes.py:41/54`; messages: `target_label` = channel) |
| `agent.tool_calls_view` | `list_tool_calls` (`tool_calls/routes.py:24`) |
| `cost.view` | `get_cost_summary` (`costs/routes.py:24`) — billing-sensitive, cheap to include |
| `audit_log.view` / `audit_log.export` | the new audit routes themselves — "who read the audit log" is standard practice |

### Exempt (in `AUDIT_EXEMPT_ROUTES`, each with a reason)

Health endpoints, `auth/me`, `auth/refresh`, `auth/signup` (stub), pure list endpoints (`list_agents`, `list_users`, `get_organizations`, `list_members`, `list_skills`, `list_templates`, `list_models`, Slack channel/user directory lookups), `get_agent_healthz` (UI polling), webhook/slack/ingest routers (agent-key auth — AF-5's domain), `google_callback`/`google_authorize_url`.

> Note: `auth.*` and superuser `user.*` events carry `organization_id = NULL`, so they appear only in the superuser view, not org-admin views (a user belongs to many orgs; fanning logins out per-org would be noise). Deliberate v1 tradeoff — revisit if org-scoped login visibility is requested.

## 4. Read API — `api/domains/audit_logs/routes.py`

`audit_logs_router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])`, registered in `api_app.py` alongside the other routers.

### `GET /api/v1/audit-logs`

```
?page=&page_size=&action=&actor_user_id=&search=&target_type=&target_id=&start_date=&end_date=&organization_id=&scope=
```

- Gate: `Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES))` — same as costs; owner/admin on the header org, superusers bypass.
- Scoping inside `AuditLogService.list_logs`:
  - default: `organization_id = context.require_current_user_organization().organization_id`;
  - **only if** `context.user.is_superuser`: honor `filters.organization_id` (any org) or `scope=all` (no org clause — includes NULL-org global events);
  - non-superusers passing those params get them **silently overridden** to their own org (matches the codebase's scoping style).
- Repository builds `select(AuditLog, Organization.name).outerjoin(Organization, Organization.id == AuditLog.organization_id)` + filter conditions, fed through `delegate.find_all_paginated_by_query(...)` with `order_by=[("created_at","desc"), ("id","desc")]`; rows mapped to `AuditLogRead` with `organization_name`.
- Returns `PaginatedItems[AuditLogRead]`, default `page_size=25`.

### `GET /api/v1/audit-logs/actions`

Returns `sorted(a.value for a in AuditAction)` — feeds the UI filter dropdown. Same gate.

### `GET /api/v1/audit-logs/export` (§5)

## 5. Export

- `StreamingResponse(service.iter_export_rows(context, filters), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit-logs-<ISO date>.csv"'})`. Starlette iterates sync generators in a threadpool (SSE precedent: `agents/routes.py:61`).
- Same filter dependency + role gate as the list endpoint; no pagination params.
- `AuditLogRepository.iter_for_export(org_scope, filters, batch_size=1000, max_rows=100_000)`: **keyset batching** — fetch 1000 rows ordered `created_at desc, id desc`, then `WHERE (created_at, id) < (last_created_at, last_id)`; one short-lived `Session` per batch (never holds a connection across the whole stream). Hard cap 100k rows; if hit, final line is `# truncated at 100000 rows — narrow the date range`.
- Columns: `timestamp, actor_email, actor_name, action, organization_id, organization_name, target_type, target_id, target_label, changed_fields (compact JSON), id`. Serialized with `csv.writer` into per-batch `io.StringIO`.
- Frontend downloads via `api.getFile(...)` and names the file client-side (avoids needing `expose_headers=["Content-Disposition"]` in CORS).

## 6. Frontend — new feature `ui/src/features/audit-logs/`

| File | Contents |
|---|---|
| `schemas.ts` | zod `AuditLogReadSchema` (camelCase per humps: `actorEmail`, `targetLabel`, `changedFields: z.record(z.unknown()).nullable()`, …), `PaginatedAuditLogsSchema` (shape from `features/users/schemas.ts`). |
| `utils.ts` | query keys, `AUDIT_PAGE_SIZE = 25`, `formatAction("agent.create") → "Agent created"` label map with dotted-string fallback. |
| `hooks/use-audit-logs.ts` | `useQuery` keyed `{scope, orgId?, filters, page}`; builds snake_case `URLSearchParams`; `api.get("/api/v1/audit-logs?...", { schema })`. Plain paged query with page buttons (costs style), not infinite scroll. |
| `hooks/use-audit-log-actions.ts` | fetches `/api/v1/audit-logs/actions`, long `staleTime`. |
| `hooks/use-audit-log-export.ts` | `api.getFile("/api/v1/audit-logs/export?...")` → `URL.createObjectURL` → programmatic `<a download>` click (pattern: `downloadTeamsAppPackage` in `features/agents/components/hire-dialog-steps.tsx`); exposes `isExporting`. |
| `components/audit-log-filters.tsx` | draft/apply filter bar mirroring `costs-dashboard.tsx`: action `<select className="af-select">` (fed by actions hook), actor search input, two `<input type="date">`, Apply + Export buttons. |
| `components/audit-log-table.tsx` | af-card table: Time, Actor (name + email), Action (label + mono code), Target (label + type caption), Org (all-orgs scope only); expandable row (chevron + `Set<string>` state like costs `toggleAgent`) showing changed-fields old→new (`"[redacted]"` rendered verbatim). Prev/Next footer. |
| `components/audit-log-dashboard.tsx` | composes the above; props `{scope:"org"} \| {scope:"all"}`; org mode calls `useRequireOrgManager()`; all-orgs mode adds an org `<select>` from existing organizations hooks. |

Pages + nav:

- `ui/src/app/dashboard/[orgId]/audit-log/page.tsx` → `<AuditLogDashboard scope="org" />`.
- `ui/src/app/dashboard/audit-logs/page.tsx` → `<SuperAdminOnly><AuditLogDashboard scope="all" /></SuperAdminOnly>` (pattern: `dashboard/users/page.tsx`).
- `ui/src/components/top-nav.tsx`: add "Audit log" to `navTabs` gated by canManage; add "Audit logs" link in the superuser menu section.
- The mock `/activity` page is **not** touched (AF-5's agent feed) — note in PR description.

## 7. Files touched

**New**

- `api/domains/audit_logs/{__init__.py, models.py, repository.py, service.py, registry.py, routes.py}`
- one alembic revision in `api/migrations/versions/`
- `api/tests/integration/test_audit_logs.py`
- `api/tests/unit/test_audit_log_service.py`
- `api/tests/unit/test_audit_route_coverage.py`
- `ui/src/features/audit-logs/{schemas.ts, utils.ts, hooks/use-audit-logs.ts, hooks/use-audit-log-actions.ts, hooks/use-audit-log-export.ts, components/audit-log-filters.tsx, components/audit-log-table.tsx, components/audit-log-dashboard.tsx}`
- `ui/src/app/dashboard/[orgId]/audit-log/page.tsx`, `ui/src/app/dashboard/audit-logs/page.tsx`

**Modified**

- `api/migrations/env.py` (model import)
- `api/api_app.py` (include router)
- Mutation instrumentation: `api/domains/{agents,organizations,templates,skills,users}/service.py`, `api/domains/users/organization_users/service.py`, `api/domains/auth/{routes.py,service.py}`, `api/domains/integrations/google_oauth/routes.py`
- Read instrumentation: `api/domains/{agents,conversations,tool_calls,costs}/routes.py`
- `ui/src/components/top-nav.tsx`

## 8. Implementation order

1. `audit_logs` domain files (models → repository → service → registry stub → routes).
2. `migrations/env.py` import; `make makemigrations`; inspect revision; `make migrate`.
3. Register the router in `api_app.py`.
4. Instrument mutations (services), then reads (routes); fill `registry.py` audited/exempt maps as each router is covered.
5. Backend tests; `make test-api`.
6. Frontend feature dir, pages, nav; `make check-ui test-ui`.
7. End-to-end verification (below), then PR.

## 9. Verification

1. Migration: revision creates `audit_log` (JSONB + 5 indexes); `make migrate` applies cleanly.
2. `make test-api`:
   - **Integration** (`test_audit_logs.py`, using `prepare_injector` + steps helpers): agent create writes an `agent.create` row with actor snapshot + org; agent update captures changed field names with token values redacted; org admin lists only own org; MEMBER → 403; cross-org isolation (mirror `test_cross_org_isolation.py`); superuser `scope=all` sees both orgs + NULL-org auth events; filters by action/date-range/actor; export returns `text/csv` with header row honoring filters; failed login writes `auth.login_failed`.
   - **Unit**: `record()` swallows repository exceptions; redaction is default-deny (unknown field → name only); read-suppression window works; `diff_changed_fields` old/new correctness; route-coverage guard passes and fails when a route is unmapped.
3. `make check-ui test-ui`.
4. **End-to-end (dev)**: run API + UI; as org admin — create/update/start an agent, open its detail page, then visit `/dashboard/<orgId>/audit-log`: rows present, update shows changed fields, single `agent.view` despite refetches; filter by action + date; Export downloads a CSV whose rows match. As superuser — `/dashboard/audit-logs`, switch orgs, `scope=all` shows login/failed-login events. As MEMBER — no nav tab; direct URL redirects.

## Risks / follow-ups (out of scope, note in PR)

- **Retention/volume**: no requirement; read suppression + exemptions bound growth. Options later: age-based purge CronJob (`DELETE WHERE created_at < now() - interval '365 days'`) or time partitioning.
- **Auth/user events invisible to org admins** (NULL org) — deliberate v1 tradeoff.
- **Offset-page drift** on a live log — acceptable for admin browsing; uuid7 enables a cursor upgrade later.
- **Tamper resistance**: append-only by construction — no update/delete API for `audit_log`.
- **Secrets/PII**: default-deny value allowlisting means new sensitive fields are safe by default; only an explicit allowlist addition (code-reviewed) can expose values.
- **IP / user-agent deliberately omitted** — not in the ticket's AC and PII-adjacent. If security forensics later wants them (most useful on `auth.login_failed`), it's two nullable columns + a migration, plus `client_ip`/`user_agent` fields on `CurrentUserContext` populated in the `get_current_user` wrapper (it already receives `request: Request`).
