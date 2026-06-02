# AF-108 — Hermes Agents Support

## Context

Agent Farm currently supports a single agent runtime (OpenClaw) running on either Slack or Teams. The ocbw predecessor supports a second runtime called **Hermes** (`nousresearch/hermes-agent`), and we now want feature parity in Agent Farm: an operator should be able to choose between OpenClaw and Hermes when creating an agent.

Hermes is a separate runtime with its own image, config format, plugin system, and Slack wiring. We add it as an orthogonal dimension to the existing `AgentPlatform` so the two concepts (which runtime, which messaging platform) compose cleanly.

### Acceptance Criteria (from Jira)
- User can choose between OpenClaw and Hermes agents during creation
- User can set up Slack channels and users like in OpenClaw
- A functional Hermes agent can be deployed in k8s

### Key Decisions
- **`AgentType` enum** (`openclaw` | `hermes`) is **orthogonal** to `AgentPlatform`. Stored as a new column on `agent`, immutable after creation.
- **Hermes is Slack-only for v1.** Validator on `AgentCreate` rejects `agent_type=hermes` with `platform=teams`.
- **Vanilla upstream Hermes image** — not a custom `hermes-base` build. The healthz sidecar and plugins are injected via ConfigMap at pod start. Rationale: Hermes ships self-contained (Python + gateway), so the only thing we add is a ~30-line healthz Python script. Building and maintaining a custom image is unjustified for v1.
- **Image pinning** — `HERMES_IMAGE` env var + `hermesImage` Helm value mirror `AGENT_IMAGE` / `openclawImage`. Default tag is `latest` initially; we'll pin to a specific Hermes version in a follow-up once we settle on one.
- **File placement mirrors ocbw**:
  - `SOUL.md` → `/opt/data/SOUL.md` (Hermes-canonical; persists in PVC)
  - `USER.md` → `/opt/data/memories/USER.md` (seed-once on first boot only — agent-mutable)
  - `IDENTITY.md, AGENTS.md, TOOLS.md, BOOT.md, HEARTBEAT.md` → `/workspace/` (reference material; agent reads via terminal)
  - `BOOTSTRAP.md` — skipped (OpenClaw-specific concept)
- **SOUL.md bootloader** — we system-inject a small footer onto whatever SOUL.md the operator wrote, instructing the agent which files live where. This is the same design principle as ocbw's default SOUL.md (*"These files are your memory. Read them."*). Keeps the operator's content portable across runtimes.
- **Two Hermes plugins** baked into the ConfigMap and dropped into `/opt/data/plugins/`:
  - `slack-deny-dms` (port of ocbw's plugin) — used when `dm_policy = off`
  - `slack-dm-allowlist` (new, written by us) — used when `dm_policy = allowlist`. Hermes's native `SLACK_ALLOWED_USERS` restricts *all* interactions; we need DM-only restriction to mirror OpenClaw's semantics.
- **Hermes Slack config mirrors OpenClaw exactly** — see Phase 4 table below. Channel allowlist scopes where the bot listens; users in those channels can interact freely. DM allowlist (when active) only filters DMs.
- **`unauthorized_dm_behavior: ignore`** in `config.yaml` — our plugins handle DM auth, so Hermes's built-in pairing is disabled.
- **API_SERVER_KEY** (Hermes gateway token) is generated fresh per `start_agent` call. Not persisted in DB.
- **Defaults** — port ocbw's `AGENTS.md`, `TOOLS.md`, `USER.md` to `defaults.py` (Jinja stripped to generic phrasing). `BOOT/HEARTBEAT/BOOTSTRAP` defaults left as-is. **No** `DEFAULT_SOUL_MD` / `DEFAULT_IDENTITY_MD` — those stay operator-required so people think about who their agent is.
- **Pairing** is being removed from OpenClaw in a separate task; this plan does not introduce it on Hermes.

### Why no custom Hermes plugin registry / image
- ocbw established the pattern of embedding small Python plugins as string constants and writing them to disk at agent bootstrap. The Hermes plugin API (`pre_gateway_dispatch` and friends) is stable enough for this.
- Maintaining two `~30`-line plugins as builders.py string constants is cheaper than another image build pipeline.
- Future audit/observability work (Epic 4 in the spec) can reuse the same plugin pattern.

---

## Phase 1: Database Migration

**New file:** `api/migrations/versions/<rev>_add_agent_type.py`

Single-statement migration:

1. Add `agent_type` column to `agent`:
   - `String(20)`, `NOT NULL`, `server_default "openclaw"`
   - CHECK constraint for `openclaw` / `hermes`

No data migration needed — existing rows backfill to `openclaw` via the server default.

---

## Phase 2: Backend Models

**File:** `api/domains/agents/models.py`

**New enum:**
```python
class AgentType(str, enum.Enum):
    OPENCLAW = "openclaw"
    HERMES = "hermes"
```

**Modified `Agent` model:**
- Add `agent_type: AgentType` with default `OPENCLAW`, `sa_column=Column(sa.String(20), nullable=False, server_default="openclaw")`

**Modified `AgentCreate`:**
- Add `agent_type: AgentType = AgentType.OPENCLAW`
- Extend `validate_platform_credentials` validator: if `agent_type == HERMES`, require `platform == SLACK`. Otherwise raise `ValueError`.

**Modified `AgentRead`:**
- Add `agent_type: AgentType`

`AgentUpdate` is unchanged — `agent_type` is immutable after creation.

---

## Phase 3: Config + Helm

**File:** `api/core/config.py`
```python
hermes_image: str = ""   # mirrors agent_image
```

**File:** `helm/agentfarm-api/values.yaml`
```yaml
hermesImage:
  repository: nousresearch/hermes-agent
  tag: latest               # TODO(AF-108): pin to a specific Hermes version once selected
```

**File:** `helm/agentfarm-api/templates/deployment.yaml`
```yaml
- name: HERMES_IMAGE
  value: "{{ .Values.hermesImage.repository }}:{{ .Values.hermesImage.tag }}"
```

**File:** `.env.example` — add `HERMES_IMAGE=nousresearch/hermes-agent:latest` line (TODO: pin to specific version once selected).

---

## Phase 4: Builders

**File:** `api/domains/agents/builders.py`

New constants (string-embedded scripts/configs):

### `HERMES_HEALTHZ_PY`
Python script: polls `http://127.0.0.1:8642/v1/models` with `Authorization: Bearer $API_SERVER_KEY` every 10s, caches result, exposes `/ready` and `/healthz` on `:8081`. Same response shape as OpenClaw's `HEALTHZ_SERVER_JS` so the existing k8s probe logic just works.

### `HERMES_START_SH`
```sh
#!/bin/sh
set -e
python3 /app/config/healthz-server.py &

mkdir -p /opt/data/memories /opt/data/plugins/slack-deny-dms /opt/data/plugins/slack-dm-allowlist /workspace

# Personality: SOUL.md (canonical) and config.yaml — overwrite from ConfigMap each restart
cp /app/config/SOUL.md /opt/data/SOUL.md
cp /app/config/hermes-config.yaml /opt/data/config.yaml

# Workspace reference files — overwrite from ConfigMap each restart
for f in IDENTITY.md AGENTS.md TOOLS.md BOOT.md HEARTBEAT.md; do
    [ -f /app/config/$f ] && cp /app/config/$f /workspace/$f
done

# USER.md is agent-mutable — seed only on first boot
[ -f /opt/data/memories/USER.md ] || cp /app/config/USER.md /opt/data/memories/USER.md

# Plugins (always restored from ConfigMap)
cp /app/config/slack-deny-dms-plugin.yaml /opt/data/plugins/slack-deny-dms/plugin.yaml
cp /app/config/slack-deny-dms-init.py    /opt/data/plugins/slack-deny-dms/__init__.py
cp /app/config/slack-dm-allowlist-plugin.yaml /opt/data/plugins/slack-dm-allowlist/plugin.yaml
cp /app/config/slack-dm-allowlist-init.py    /opt/data/plugins/slack-dm-allowlist/__init__.py

exec gateway run
```

### `HERMES_BOOTLOADER_FOOTER`
Appended to the operator's SOUL.md before writing to the ConfigMap:
```
---

# System

You wake up fresh each session. Your operator has placed reference files on disk:

- `/workspace/IDENTITY.md` — who you are
- `/workspace/AGENTS.md` — workspace conventions and red lines
- `/workspace/TOOLS.md` — tool notes
- `/workspace/BOOT.md` — startup behavior
- `/workspace/HEARTBEAT.md` — heartbeat behavior
- `/opt/data/memories/USER.md` — about your human
- `/opt/data/memories/MEMORY.md` — your long-term memory (write here to persist)

Read what's relevant for the current task. Update files in `/opt/data/memories/` to persist learnings across restarts.
```

### `SLACK_DENY_DMS_PLUGIN_YAML` / `SLACK_DENY_DMS_PLUGIN_PY`
Direct port of ocbw's `hermes.py:17-91`. Hooks `pre_gateway_dispatch`, drops Slack DMs when `SLACK_DENY_DMS=true` is present in env.

### `SLACK_DM_ALLOWLIST_PLUGIN_YAML` / `SLACK_DM_ALLOWLIST_PLUGIN_PY`
New plugin. Hooks `pre_gateway_dispatch`. Reads `SLACK_DM_ALLOWED_USERS` (comma-separated). If event is a Slack DM from a user not in the allowlist, returns `{"action": "skip", "reason": "slack-dm-not-allowlisted"}`. All non-DM events pass through.

```python
"""Drop Slack DMs from users not in SLACK_DM_ALLOWED_USERS."""
import os

def _allowed_ids():
    return {x.strip() for x in os.getenv("SLACK_DM_ALLOWED_USERS", "").split(",") if x.strip()}

def filter_dm_allowlist(event, gateway=None, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    platform = str(getattr(source, "platform", "") or "").lower()
    chat_type = str(getattr(source, "chat_type", "") or "").lower()
    if platform != "slack" or chat_type != "dm":
        return None
    sender = str(getattr(source, "user_id", "") or "")
    if sender and sender in _allowed_ids():
        return None
    return {"action": "skip", "reason": "slack-dm-not-allowlisted"}

def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", filter_dm_allowlist)
```

### `build_hermes_config(model, litellm_base_url) -> dict`
Returns the dict written to `/opt/data/config.yaml`. Mirrors ocbw's `build_hermes_config` but skips the firecrawl branch (out of scope for v1).

Key fields:
- `toolsets: ["all"]`
- `model`: provider/default/base_url derived from `model` arg
- `terminal.cwd: /workspace`
- `memory.memory_enabled: true`
- `compression.enabled: true`
- `display.tool_progress: all`, `display.platforms.slack.tool_progress: off`
- `slack.reply_in_thread: true`, `slack.require_mention: true`, `slack.unauthorized_dm_behavior: ignore`
- `plugins.enabled: ["slack-deny-dms", "slack-dm-allowlist"]` (both registered; their env-var gates decide whether they actually filter)

### `build_hermes_config_map(...)`
Returns `V1ConfigMap` containing:
- 7 personality .md files (excluding BOOTSTRAP.md): SOUL.md (with bootloader footer appended), IDENTITY.md, USER.md, TOOLS.md, AGENTS.md, BOOT.md, HEARTBEAT.md
- `hermes-config.yaml` (JSON-dumped `build_hermes_config` result; the start.sh copies it as YAML... actually we'll serialize as YAML directly via `yaml.safe_dump`)
- `start.sh`, `healthz-server.py`
- 4 plugin files (2 per plugin)

### `build_secret_hermes_slack(...)`
Returns `V1Secret` with:
- `OPENAI_API_KEY` = litellm virtual key
- `OPENAI_BASE_URL` = agent_litellm_base_url
- `API_SERVER_KEY` = freshly generated token
- `API_SERVER_MODEL_NAME` = agent name
- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
- `SLACK_ALLOW_ALL_USERS` = `"true"` (always; we use plugins for filtering)
- `SLACK_HOME_CHANNEL` (optional)
- `SLACK_ALLOWED_CHANNELS` (optional, only when `group_policy=allowlist`)
- `SLACK_DENY_DMS` = `"true"` only when `dm_policy=off`
- `SLACK_DM_ALLOWED_USERS` (optional, only when `dm_policy=allowlist`)

### `build_hermes_deployment(...)`
Mirrors `build_deployment` but with:
- image = `config.hermes_image`
- command = `["sh", "/app/config/start.sh"]` (same as OpenClaw)
- Volume mounts:
  - ConfigMap → `/app/config` (read-only)
  - PVC → `/opt/data`
  - emptyDir → `/workspace`
- Readiness probe `/ready:8081` (unchanged from OpenClaw — same probe interface)

### Slack→Hermes Config Mapping (mirrors OpenClaw semantics exactly)

| AgentSlackConfig | Hermes wiring |
|---|---|
| always | `SLACK_ALLOW_ALL_USERS=true` |
| `group_policy = open` | no `SLACK_ALLOWED_CHANNELS`; bot responds in any channel it's invited to |
| `group_policy = allowlist` | `SLACK_ALLOWED_CHANNELS=channel_ids` (comma-joined) |
| `dm_policy = off` | `SLACK_DENY_DMS=true` (slack-deny-dms plugin filters) |
| `dm_policy = open` | (no env; both plugins idle) |
| `dm_policy = allowlist` | `SLACK_DM_ALLOWED_USERS=dm_user_ids` (slack-dm-allowlist plugin filters DMs) |
| `dm_policy = pairing` | reject — being removed from OpenClaw |
| `channel_ids[0]` if present | `SLACK_HOME_CHANNEL=...` |

Resulting behavior (identical to OpenClaw):

| Scenario | Outcome |
|---|---|
| User in allowlisted channel @mentions bot | bot responds |
| User in non-allowlisted channel @mentions bot | silently ignored |
| Allowlisted DM user messages bot | bot responds |
| Non-allowlisted DM user messages bot | dropped by plugin |
| Any user in channel when `group_policy=open` | bot responds |

---

## Phase 5: Service Layer

**File:** `api/domains/agents/service.py`

### `start_agent`
Add a third branch alongside `OPENCLAW + SLACK` and `OPENCLAW + TEAMS`:

```python
elif agent.agent_type == AgentType.HERMES and agent.platform == AgentPlatform.SLACK:
    slack_config = self.repository.get_slack_config(agent.id)
    # ... decrypt tokens ...
    api_server_key = secrets.token_urlsafe(32)
    overlay = build_hermes_config(effective_model, self.config.agent_litellm_base_url)
    secret = build_secret_hermes_slack(
        agent_id=agent.id, org_id=org_id, namespace=ns,
        slack_bot_token=bot_token, slack_app_token=app_token,
        api_server_key=api_server_key,
        litellm_api_key=litellm_key,
        litellm_base_url=self.config.agent_litellm_base_url,
        agent_name=agent.name,
        slack_channel_ids=slack_config.channel_ids,
        slack_dm_user_ids=slack_config.dm_user_ids,
        slack_group_policy=str(slack_config.group_policy),
        slack_dm_policy=str(slack_config.dm_policy),
    )
    config_map = build_hermes_config_map(
        agent_id=agent.id, org_id=org_id, namespace=ns,
        soul_md=template.soul_md,
        identity_md=template.identity_md,
        user_md=template.user_md,
        tools_md=template.tools_md,
        agents_md=template.agents_md,
        boot_md=template.boot_md,
        heartbeat_md=template.heartbeat_md,
        hermes_config_overlay=overlay,
    )
    service = build_service(agent.id, org_id, ns)  # no webhook port for Slack
    deployment = build_hermes_deployment(agent.id, org_id, ns, self.config.hermes_image, self.config.agent_image_pull_secret)
```

The existing OpenClaw branches build a `build_deployment(...)` with `self.config.agent_image`; the Hermes branch uses `self.config.hermes_image` via `build_hermes_deployment(...)`.

### `_build_agent_read`
Include `agent_type` in the returned `AgentRead`.

### `update_agent`
- `agent_type` is immutable — no field to update.
- Existing cross-platform field rejection (`_SLACK_CONFIG_FIELDS` / `_TEAMS_CONFIG_FIELDS`) is unchanged.

### Other methods
- `stop_agent`, `delete_agent` — already use the agent's deployment name (`agent-{uuid}`) and don't care about runtime. No changes.
- `pair_agent` — stays Slack/OpenClaw-only; add a check `if agent.agent_type != AgentType.OPENCLAW: raise 400`.
- `list_slack_channels` / `list_slack_users` — runtime-agnostic; no change.

---

## Phase 6: Defaults

**File:** `api/domains/agents/defaults.py`

Replace existing minimal stubs for:
- `DEFAULT_AGENTS_MD` — port ocbw's `profiles/default/AGENTS.md` (113 lines: memory routines, red lines, group chat rules, heartbeats)
- `DEFAULT_TOOLS_MD` — port ocbw's `profiles/default/TOOLS.md` (rules about narrowest tool, confirming destructive actions)
- `DEFAULT_USER_MD` — port ocbw's `profiles/default/USER.md` (fill-in-the-blank scaffold for human details)

Leave unchanged:
- `DEFAULT_BOOT_MD`, `DEFAULT_HEARTBEAT_MD`, `DEFAULT_BOOTSTRAP_MD` — current stubs are comparable to ocbw's

Do NOT add:
- `DEFAULT_SOUL_MD` / `DEFAULT_IDENTITY_MD` — stay operator-required so people actually write a real personality.

**Jinja:** ocbw uses `{{ agent_display_name }}` etc. — strip to generic phrasing ("you", "the agent") so defaults are static strings.

---

## Phase 7: API Tests

**Files under `api/tests/`**

### Builder unit tests (`tests/domains/agents/test_builders.py`)
Fast, isolated coverage of the dict/manifest output — avoids stacking service + k8s mocks for every case.

- `test_build_hermes_config_has_expected_top_level_keys` — `toolsets`, `model`, `terminal`, `memory`, `slack.unauthorized_dm_behavior == "ignore"`, `plugins.enabled` contains both plugin names
- `test_build_hermes_config_map_includes_all_files` — ConfigMap data has the 7 .md files (no BOOTSTRAP.md), `hermes-config.yaml`, `start.sh`, `healthz-server.py`, and the 4 plugin files
- `test_build_hermes_config_map_appends_bootloader_footer_to_soul` — SOUL.md content in ConfigMap contains both operator text and the bootloader footer
- `test_build_secret_hermes_slack_dm_policy_off` — string_data has `SLACK_DENY_DMS=true`, `SLACK_ALLOW_ALL_USERS=true`, no `SLACK_DM_ALLOWED_USERS`
- `test_build_secret_hermes_slack_dm_policy_open` — neither `SLACK_DENY_DMS` nor `SLACK_DM_ALLOWED_USERS`; `SLACK_ALLOW_ALL_USERS=true`
- `test_build_secret_hermes_slack_dm_policy_allowlist` — `SLACK_DM_ALLOWED_USERS=u1,u2`, no `SLACK_DENY_DMS`
- `test_build_secret_hermes_slack_group_policy_allowlist` — `SLACK_ALLOWED_CHANNELS=c1,c2`
- `test_build_secret_hermes_slack_group_policy_open` — no `SLACK_ALLOWED_CHANNELS`
- `test_build_secret_hermes_slack_home_channel_from_first_channel_id` — `SLACK_HOME_CHANNEL=c1` when `channel_ids=["c1","c2"]`
- `test_hermes_plugin_strings_are_valid_python` — `compile(SLACK_DENY_DMS_PLUGIN_PY, ...)` and same for `SLACK_DM_ALLOWLIST_PLUGIN_PY`; fails fast on typos
- `test_hermes_start_sh_invokes_gateway_run` — `HERMES_START_SH` contains the `exec gateway run` line

### Service / integration tests (`tests/domains/agents/test_routes.py` style)

**Happy paths:**
- `test_create_agent_hermes_slack_happy_path` — POST 201, response has `agent_type=hermes`
- `test_create_agent_defaults_to_openclaw` — POST without `agent_type` field returns agent with `agent_type=openclaw` (back-compat)
- `test_start_agent_hermes_uses_hermes_image` — mocks k8s; asserts the Deployment manifest uses `config.hermes_image`
- `test_update_agent_hermes_model_and_template` — PATCH model and personality fields work
- `test_stop_agent_hermes` — deletes deployment; status flips to STOPPED
- `test_delete_agent_hermes` — soft-deletes; k8s teardown runs
- `test_list_slack_channels_works_for_hermes` — runtime-agnostic; happy path
- Existing OpenClaw tests must still pass — `agent_type` defaults to `openclaw` everywhere

**Validation failures (422):**
- `test_create_agent_hermes_teams_rejected` — platform/type mismatch
- `test_create_agent_hermes_missing_slack_tokens` — `agent_type=hermes`, `platform=slack`, no `slack_bot_token` / `slack_app_token` → 422
- `test_create_agent_invalid_agent_type` — `agent_type="bogus"` → 422 from Pydantic enum coercion
- `test_create_agent_missing_required_personality_fields` — no `soul_md` or `identity_md` → 422 (covers both runtimes)
- `test_update_agent_cannot_change_agent_type` — PATCH with `agent_type` field is rejected (or silently ignored — assert immutable behavior)
- `test_update_agent_hermes_rejects_teams_fields` — PATCH `teams_app_id` on a hermes/slack agent → 422

**Auth failures (401 / 404):**
- `test_create_agent_hermes_requires_auth` — no token → 401
- `test_get_agent_hermes_from_other_org_not_found` — agent exists in org A, user in org B → 404
- `test_start_agent_hermes_from_other_org_not_found` — same scoping for start endpoint

**Not-found (404):**
- `test_get_agent_hermes_nonexistent_id` — random UUID → 404
- `test_start_agent_hermes_after_delete` — operations on soft-deleted agent → 404

**State conflicts (409):**
- `test_start_agent_hermes_already_running` — RUNNING → 409
- `test_stop_agent_hermes_not_running` — STOPPED → 409
- `test_update_agent_hermes_while_running` — RUNNING → 409 (existing rule, verify it covers hermes)

**Infrastructure failures (503 / 500):**
- `test_create_agent_hermes_litellm_failure` — `LiteLLMClient.generate_key` raises → 503; no agent row persisted
- `test_start_agent_hermes_k8s_failure_sets_error_status` — `KubernetesClient.create_deployment` raises → agent row updated to `ERROR`, 500 returned
- `test_start_agent_hermes_missing_slack_config` — agent row exists but `agent_slack_config` row missing → 500 (defensive)

**Other (400):**
- `test_pair_endpoint_rejects_hermes_agent` — POST /pair returns 400 with clear "pairing is OpenClaw-only" reason

### Migration test (`tests/migrations/test_agent_type_backfill.py`)
One minimal test asserting the `server_default` actually applies:
- `test_existing_agent_rows_backfill_to_openclaw` — insert a row into `agent` without specifying `agent_type` (simulating a pre-migration row), then read it back and assert `agent_type == "openclaw"`. Catches the realistic failure mode (missing or wrong `server_default`) without introducing a full round-trip pattern this codebase doesn't yet use.

The rest of the migration is implicitly exercised by `tests/conftest.py:31-41` running `alembic upgrade heads` per test session.

---

## Phase 8: UI

**Files under `ui/src/features/agents/`**

### `schemas.ts`
```ts
export const AgentType = z.enum(["openclaw", "hermes"]);
export type AgentType = z.infer<typeof AgentType>;

// extend agentSchema:
agent_type: AgentType
// extend AgentCreate payload schema similarly
```

### `hire-dialog.tsx`
- Add an agent-type selector as the first step (or just above the platform selector)
- Default: OpenClaw
- When `agent_type=hermes`:
  - Platform selector is locked to Slack (Teams disabled with tooltip "Teams not supported for Hermes agents")
  - All other steps unchanged (Slack credentials, template, model)

### Agent display
- Show agent type alongside platform on agent detail / card (small badge or label)

### Playwright
- Existing OpenClaw flows still pass (agent_type defaults to openclaw)
- New spec: create Hermes agent via wizard, verify agent_type=hermes in detail view, verify Teams option disabled when Hermes selected

---

## Phase 9: Validation

Run from repo root:
- `make check-api` — lint, types, formatting
- `make test-api` — full backend test suite
- `make lint-ui`
- `cd ui && pnpm -s tsc --noEmit`
- `cd ui && pnpm test` (Playwright)

---

## Out of Scope (Future Tickets)

- **Hermes + Teams** — Teams adapter for Hermes is not part of v1
- **Hermes-specific config knobs** (firecrawl, custom toolsets, terminal_timeout) — could expose via `AgentUpdate` later
- **Audit/observability plugin** — Epic 4 (AWM-4.1) will reuse the plugin pattern established here
- **Pinning ocbw-style profile distributions** — ocbw has a profile registry concept; out of scope
- **Removing pairing from OpenClaw** — separate ticket; this plan ignores pairing

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Hermes plugin API changes break our string-embedded plugins | Pin `HERMES_IMAGE` to a specific version; add a smoke test that exercises plugin registration on startup |
| Operator forgets to invite bot to `SLACK_HOME_CHANNEL` after agent start | Cron-related features fail gracefully; surface via health check in a follow-up |
| `SOUL.md` bootloader footer + operator content exceeds Hermes's prompt-scanner truncation threshold | Footer is ~15 lines; manageable for v1. Long-term, runtime-specific template fields. Flag for follow-up if dogfooding hits truncation. |
| Mixed runtime fleet: OpenClaw and Hermes agents share the same namespace + image-pull-secret | OK — they're independent Deployments with distinct names and labels. K8s isolation already handles this. |
| Existing OpenClaw agents at upgrade time | Migration server_defaults `agent_type=openclaw` — zero-touch for existing agents. |

---

## Branch + Commits

- Branch: `AF-108-hermes-agents-support`
- One commit per phase, ideally; final review pass squashes if needed.
- No co-author lines.
- Present-tense commit messages.
