# Templates domain: CRUD + seeding + frontend wiring

## Context

Templates became org-scoped versioned lineages (slug + version) in the previous refactor, but they're still created per-agent and the catalog (Scrum Master / PR Reviewer profiles) lives as hardcoded TS constants in the UI. This change makes templates first-class shared resources **in their own backend domain `api/domains/templates/`** (user decision — all template management code moves out of `api/domains/agents/`, including a dedicated `TemplateRepository`):

- **Reference model (user decision)**: hiring no longer creates a template. `AgentCreate` sends `template_slug`; the agent pins to the lineage's **latest version**. Any md edit (agent config drawer OR templates page) creates a **new version** of the shared lineage; drawer edits also re-pin that agent. Other agents keep their pins.
- **Pre-defined seeding**: 3 templates — `general-purpose`/"General Purpose" (from UI `TEMPLATE_FILES.t_default`), `scrum-master`/"Scrum Master", `code-reviewer`/"PR Reviewer" (from `ui/src/features/agents/profiles/*.ts`) — seeded v1, `template_source=pre-defined`, check-by-slug-insert-if-absent, into the default org at startup AND into every new org at signup.
- **New columns**: `template_name` (display), `template_source` enum `pre-defined|custom` (String(20) pattern like `agent_type`). Table name stays `agent_template` (no rename churn).
- **TemplateRenderer (backend)**: `{{ placeholder }}` substitution moves from frontend hire-submit to backend **seed time** (`start_agent`). Templates stored/displayed/edited RAW (placeholders visible; user can break them — accepted). Unknown placeholders pass through.
- **Hire wizard**: fetches templates from API (pre-defined tagged), md is **read-only preview**, `fill()` deleted. Required-integrations enforcement **removed** (accepted regression).
- **Templates page (settings panel made real)**: list with **search + source filter**; clicking a template opens a detail drawer with md previews + name + version (**version displayed, never editable**); **Edit template** button switches previews to editable fields; **Save** creates a new version. **New template** creates v1 custom. **No delete** for now.
- Keep frontend mocks not covered by this work (SKILLS, PROVIDERS, other settings panels).

### Domain layout & import direction

```
api/domains/templates/
  __init__.py
  models.py        # AgentTemplate table class (moved), TemplateSource, TemplateCreate,
                   # TemplateUpdate, TemplateRead (renamed from AgentTemplateRead), TemplateFilter
  repository.py    # TemplateRepository: save_template, get_template_by_slug_and_version,
                   # get_template_or_raise, get_latest_template, find_latest_templates
  service.py       # TemplateService: list/get/create/update + seed_predefined_templates
  routes.py        # templates_router (prefix /templates)
  renderer.py      # render_template(template, agent_name: str) -> RenderedTemplate
  seeding.py       # build_predefined_templates(org_id) (pure; used by service + auth signup)
  slug.py          # slugify() + generate_template_slug() (moved from agents)
  defaults.py      # DEFAULT_*_MD + AAI_CLI_TOOLS_POINTER (moved from agents; add DEFAULT_SOUL_MD,
                   # DEFAULT_IDENTITY_MD)
  predefined/      # general_purpose.py, scrum_master.py, code_reviewer.py, __init__.py registry
```

Import direction (cycle-free, verified): **agents → templates**, **auth.service → templates.seeding**, **templates.routes → auth.utils** (get_current_user; auth.utils does not import auth.service). The templates domain imports NOTHING from agents — that's why `render_template` takes `agent_name: str`, not an `Agent`. Agent's composite FK references the `agent_template` table by name strings, so no model import is needed there either.

### Verified facts (don't re-derive)
- Lifespan: [api/api_app.py](api/api_app.py) lines 37-72 — `ensure_default_superuser()`, `ensure_default_organization()`, `set_default_org_id()`; routers registered ~97-103; injector via `create_injector()`.
- Runtime org creation happens ONLY in `AuthService._create_signup_user_and_organization` (api/domains/auth/service.py:109-142), user+org+org_user in ONE session, `session.commit()` at line 140. No POST /organizations endpoint.
- `start_agent`: the ConfigMap built early in each branch is DEAD CODE — unconditionally rebuilt at service.py:735-770 (hermes 737-752, openclaw/teams else 754-770). Delete the three early builds (~580-592, ~632-645, ~682-695); only the final site consumes template md.
- ConfigMap content assertions exist via mocked k8s: `test_start_agent_configmap_and_overlay_are_correct` (test_agents.py:1006), `test_start_hermes_agent_configmap_has_hermes_config` (:1772). Fixtures contain no placeholders (render = identity); no test asserts TOOLS.md equality → pointer append safe.
- `TestClient(app)` created WITHOUT context manager (api/tests/core/modules.py:28-32) → lifespan never runs in tests; test seeding by calling the service directly.
- SQLAlchemy pinned 2.0.49: `select(...).distinct(col)` renders Postgres `DISTINCT ON`.
- Profiles: both have 7 md fields (no `bootstrap_md`), only 4 placeholders (`agent_display_name`, `agent_name`, `slack_app_display_name`, `deploy_date`), contain `` \` `` escapes to unescape, zero `${`. `t_default` has only soul/identity/user/tools.
- Frontend fill() (being deleted): hire-dialog.tsx:184-192; vars: `agent_display_name`=name, `agent_name`=slug(name)||"agent", `slack_app_display_name`=botName||name, `deploy_date`=ISO date. botName NOT persisted → backend uses `agent.name` for both name vars.
- `getSteps()`/`stepOrdinal` live in hire-dialog.tsx (38-55); ROLES/pickDefaults/RoleStep in hire-dialog-steps.tsx.
- Migration head: `a4d7c2e8f1b3`.
- IMPLEMENTATION CHECK: verify how `api/migrations/env.py` discovers models (SQLModel metadata import chain) so the moved `templates/models.py` stays registered; same for any central model-import module.

## Phase A — Backend

**A1. Create templates domain — models** (`api/domains/templates/models.py`):
- MOVE `AgentTemplate` table class here from agents/models.py unchanged (class name + `__tablename__ = "agent_template"` kept), ADD `template_name: str = SqlField(nullable=False, max_length=255)` and `template_source` (default CUSTOM, `sa_column=Column(sa.String(20), nullable=False, server_default="custom")`).
- `TemplateSource(str, enum.Enum)`: `PRE_DEFINED = "pre-defined"`, `CUSTOM = "custom"`.
- `TemplateRead` (rename of `AgentTemplateRead`; += `template_name`, `template_source`) — used by both `/templates/*` and agents' `GET /agents/{id}/template/{version}`.
- `TemplateCreate` (template_name required 1..255, 8 optional md), `TemplateUpdate` (all optional incl. template_name; validator: at least one field via `model_fields_set`), `TemplateFilter(search, source)` + `get_template_filter` Query dependency (mirror `AgentFilter`).
- agents/models.py: remove AgentTemplate + AgentTemplateRead; `AgentCreate` DELETES the 8 md fields, ADDS `template_slug: str = Field(min_length=1, max_length=255)`. `AgentUpdate` unchanged.
- MOVE `slug.py` and `defaults.py` from agents → templates (add minimal `DEFAULT_SOUL_MD`/`DEFAULT_IDENTITY_MD`); extract `slugify()` base from `generate_template_slug`. Update all importers (agents service drops these imports anyway; tests/steps update paths).

**A2. Migration** (new file, `down_revision = "a4d7c2e8f1b3"`, hand-written):
- add `template_name` nullable → `UPDATE agent_template SET template_name = template_slug` (legacy lineages display as slug — accepted) → NOT NULL.
- add `template_source` `sa.String(20) nullable=False server_default='custom'` (backfills in one step) + check constraint `ck_agent_template_template_source IN ('pre-defined','custom')` (agent_type migration c1d2e3f4a5b6 pattern).
- downgrade: drop check, drop both columns.

**A3. Renderer** (`api/domains/templates/renderer.py`): `RenderedTemplate` frozen dataclass (8 str fields) + `render_template(template: AgentTemplate, agent_name: str) -> RenderedTemplate`. Regex `\{\{\s*(\w+)\s*\}\}`; vars: `agent_display_name`=agent_name, `agent_name`=`slugify(agent_name) or "agent"`, `slack_app_display_name`=agent_name, `deploy_date`=`date.today().isoformat()`; unknown placeholders pass through (`variables.get(m.group(1), m.group(0))`). Appends `AAI_CLI_TOOLS_POINTER` to tools_md idempotently (`if pointer not in tools_md`).

**A4. TemplateRepository** (`api/domains/templates/repository.py`, `@inject @singleton @dataclass` over `PostgresRepositoryDelegate` like AgentRepository):
- MOVE from AgentRepository: `save_template`, `get_template_by_slug_and_version`, `get_template_or_raise` (AgentRepository keeps only agent/config/secret/skill methods; AgentService + AgentService-dependent code gets `template_repository: TemplateRepository` injected as an additional dataclass field).
- NEW `get_latest_template(org_id, slug)` (order version desc, first).
- NEW `find_latest_templates(org_id, template_filter, pagination) -> (list, total)`: inner latest-per-slug via `.distinct(col(AgentTemplate.template_slug))` ordered `(template_slug asc, version desc)` org-scoped, wrapped as **subquery**; outer applies `search` (`ilike %…%` on template_name OR template_slug) + `source` equality on the LATEST rows, orders by template_name asc, paginates; count over same filtered subquery.

**A5. Pre-defined content + seeding** (`api/domains/templates/predefined/` + `seeding.py`):
- `predefined/`: `general_purpose.py` (t_default 4 fields + DEFAULT_AGENTS/BOOT/BOOTSTRAP/HEARTBEAT_MD), `scrum_master.py`, `code_reviewer.py` (7 fields each + DEFAULT_BOOTSTRAP_MD), `__init__.py` with `PredefinedTemplate` frozen dataclass + `PREDEFINED_TEMPLATES` registry. Port md from TS: triple-quoted strings, **unescape `` \` `` → backtick**, keep `{{ }}` literal; spot-diff backtick-heavy sections (scrum-master.ts:34, code-reviewer.ts:116-124) after porting.
- `seeding.py`: pure `build_predefined_templates(org_id) -> list[AgentTemplate]` (source=PRE_DEFINED, version=1).

**A6. TemplateService** (`api/domains/templates/service.py`, deps: `TemplateRepository`):
- `list_templates(template_filter, pagination, context)` → `PaginatedItems[TemplateRead]`.
- `get_template(slug, context)` → latest or 404.
- `create_template(data, context)`: `slug = slugify(template_name)`; empty → 422; exists → 409; v1 CUSTOM with md defaults (`data.soul_md or DEFAULT_SOUL_MD`, …).
- `update_template(slug, data, context)`: latest or 404; new row version+1, merged md, name updatable, `template_source=old.template_source`, slug immutable; never touches agent pins.
- `seed_predefined_templates(org_id)`: per predefined, `if get_latest_template(org_id, slug) is None: save_template(...)` — idempotent, never clobbers edits.

**A7. Routes** (`api/domains/templates/routes.py`, mirror agents/routes.py conventions): `templates_router = APIRouter(prefix="/templates")`; `GET ""` (page/page_size + `Depends(get_template_filter)`), `POST ""` → 201, `GET "/{slug}"`, `PATCH "/{slug}"`. No DELETE. Register in api_app.py next to agents_router.

**A8. AgentService surgery** ([api/domains/agents/service.py](api/domains/agents/service.py), now importing from `api.domains.templates.*`):
- `create_agent`: after `_check_slack_tokens`, BEFORE LiteLLM key gen: `template = self.template_repository.get_latest_template(org_id, data.template_slug)` → **404** if None (dangling reference; matches get_agent_template convention; no orphaned LiteLLM key). `Agent(..., template_slug=template.template_slug, template_version=template.version)`. DELETE template-creation block + AAI pointer append + "save template before agent" comment + now-unused imports.
- `update_agent` md branch: switch to `template_repository.get_template_or_raise`; new version row += `template_name=old_template.template_name, template_source=old_template.template_source`.
- `get_agent_template`: switch to `template_repository.get_template_by_slug_and_version`; response model `TemplateRead`.
- `start_agent`: `rendered = render_template(template, agent.name)` after the template fetch; DELETE the three dead early ConfigMap builds; final build site (735-770) uses `rendered.X`.

**A9. Seeding wiring**:
- Lifespan (api_app.py), inside the existing try, after `set_default_org_id(...)`: `injector.get(TemplateService).seed_predefined_templates(default_org.id)`.
- Signup (auth/service.py `_create_signup_user_and_organization`), inside the transaction after the org_user `save_with_session`, before `session.commit()`: `for t in build_predefined_templates(organization.id): session.add(t)` (atomic with org creation; import `api.domains.templates.seeding`).

## Phase B — Backend tests

- **steps**: new `api/tests/steps/template.py` with `there_is_a_template(slug, name, version, source, **md)` setting `context.template`. `steps/agent.py`: update imports (templates domain paths), `there_is_an_agent` template gains `template_name=name, template_source=CUSTOM` + optional `soul_md`/`tools_md` params (for renderer tests); template saves go through `TemplateRepository`.
- **test_agents.py**: `_GIVEN` += `there_is_a_template()`; `_VALID_CREATE*` payloads drop soul/identity md, add `"template_slug": "test-template"`. Replace: missing-soul/identity 422 tests → `missing_template_slug_returns_422` + `unknown_template_slug_returns_404`; defaults test → `create_pins_latest_template_version` (seed v1+v2 → pin 2) + `create_does_not_create_template_rows`. New start_agent assertions: agent with `soul_md="# Soul of {{ agent_display_name }}"`, `tools_md="T {{ unknown }}"` → ConfigMap SOUL.md rendered, TOOLS.md keeps `{{ unknown }}` and ends with pointer exactly once.
- **New test_templates.py** (integration, `_BASE=/api/v1/templates`): list (latest-per-slug, org-scoped, pagination, search by name/slug substring, source filter, 401); get (latest, fields incl. name/source, 404); create (201 v1 custom slugified, md defaults, 409 dup slug, same name across orgs OK, 422 empty/all-symbol name); update (version+1 merged, name editable + slug immutable, pre-defined source preserved, pinned agents untouched, 404, 422 empty body); seeding (direct service call → exactly 3 pre-defined v1 slugs general-purpose/scrum-master/code-reviewer; idempotent; edit-then-reseed keeps v2); signup → new org has the 3 lineages; lifecycle: two agents on one slug, drawer-PATCH one → only that agent re-pins, `GET /templates/{slug}` returns bumped version.
- **New unit test_template_renderer.py** (hamcrest): all 4 vars, spacing variants, unknown passthrough, slugify fallback "agent", pointer idempotency; unit tests for `slugify`.

## Phase C — Frontend

- **C1 Schemas/keys** ([schemas.ts](ui/src/features/agents/schemas.ts)): `AgentTemplateReadSchema` += `templateName: z.string()`, `templateSource: z.enum(["pre-defined","custom"])` (zod-required → update ALL mocks); `PaginatedTemplatesSchema`. [utils.ts](ui/src/features/agents/utils.ts): `templatesKey` + page size.
- **C2 Hooks** (mirror existing patterns): `use-templates.ts` (GET `/api/v1/templates` with `search`/`source` params included in queryKey), `use-template.ts`, `use-create-template.ts`, `use-update-template.ts` (invalidate `templatesKey`). `use-create-agent.ts`: `CreateAgentData` drops 8 md fields, adds `templateSlug`. `use-update-agent.ts`: also invalidate `templatesKey.lists()` (drawer saves publish a new catalog latest).
- **C3 Hire wizard**: hire-dialog-steps.tsx — delete `ROLES`/`pickDefaults`/`RoleStep`; add `TemplateStep` using `useTemplates()` (cards: templateName, slug, "Pre-defined" badge, loading/empty states, auto-select first). `DetailsStep`: md textareas → read-only tabbed preview of all 8 fields. hire-dialog.tsx — `selectedTemplate` state replaces md states + `pick`; DELETE `fill()`/vars and required-integration pre-seeding (106-111) and `allRequiredGroupsSatisfied` gating (keep `hasIncompleteIntegration`); submit posts `{name, model, platform, agentType, templateSlug, secrets, ...tokens}`; step id `role` → `template` (keep title text + "Aria" default name/placeholders to minimize e2e churn). `IntegrationsStep`: strip required-group machinery; [integrations.ts](ui/src/features/agents/integrations.ts): remove `RequiredIntegrationGroup`/`allRequiredGroupsSatisfied`; config-drawer call site drops `requiredGroups`.
- **C4 Templates page** (settings TemplatesPanel made real): new `templates-panel.tsx` — search input + source filter (All / Pre-defined / Custom) driving `useTemplates`; rows: templateName · `slug@vN` · source badge; **row click opens detail drawer**; "New template" button. New `template-drawer.tsx` (modeled on config-drawer): **preview mode** = name, `slug@vN` (version display-only), source badge, 8 md file tabs read-only; **"Edit template"** switches name + md to editable fields; **"Save"** → PATCH (new version) → back to preview with bumped version; create mode = editable from start with derived-slug preview → POST; surface 409. [settings/page.tsx](ui/src/app/dashboard/settings/page.tsx): replace inline mock TemplatesPanel (280-305) with the real component.
- **C5 Cleanup**: delete `ui/src/features/agents/profiles/` (both files), `TEMPLATES` + `TEMPLATE_FILES` from [data.ts](ui/src/features/agents/data.ts) (KEEP `SKILLS`, `PROVIDERS`), mock `AgentTemplate` interface from types.ts.

## Phase D — Playwright

- **agent-data-support.po.ts**: `mockAgentTemplate` += `template_name`/`template_source`; add `mockTemplates` (2 pre-defined + 1 custom) + `interceptGetTemplatesRequest` (`**/api/v1/templates*`), `interceptGetTemplateRequest`, `interceptCreateTemplateRequest`, `interceptUpdateTemplateRequest`.
- **hire-dialog.spec.ts**: `beforeEach` += templates intercept; DELETE the "scrum-master pre-seeds required integrations" test (regression accepted); add: cards render with Pre-defined badge; details step read-only; hire POST body has `template_slug` and no `soul_md` (`waitForRequest` + `postDataJSON`).
- **New settings-templates.spec.ts** (+ minimal settings page PO): list renders; search filters rows; source filter works; row click → preview drawer (version shown, not editable); Edit → fields editable → Save → PATCH asserted; New → POST asserted; 409 surfaced.

## Verification

```
make check-api   # ruff + format + ty
make test-api    # testcontainers + alembic heads → migration + all behavior
make check-ui    # tsc
make lint-ui
make test-ui     # playwright
```
Manual: `make migrate` on dev DB; boot api (`make dev-api`) → verify 3 pre-defined templates for default org via GET /templates; optional downgrade/upgrade cycle via throwaway container.

## Risks / accepted trade-offs

- Legacy per-agent lineages appear in the catalog named by slug (e.g. `maya-3f9a2c1b`, custom) — accepted; renameable via edit.
- Drawer md edits publish a new catalog "latest" silently — approved design; codified by lifecycle test.
- POST /templates race: pre-check + unique constraint; concurrent dup → IntegrityError 500 (optionally catch → 409).
- Hire wizard loses Data Analyst / Sales Research starter profiles (thin mocks) — recreatable as custom templates.
- DISTINCT ON ordering handled via subquery wrapper (orders by template_name).
- TS→Python md porting fidelity (backtick unescaping) — spot-diff after porting.
- Moving models/defaults/slug across domains touches many imports — purely mechanical; `make check-api` (ty) catches stragglers; verify alembic env.py still sees the moved table model.
