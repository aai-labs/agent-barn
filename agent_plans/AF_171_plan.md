# Telegram Support for Agent Farm (Hermes + OpenClaw Runtimes)

## Context

Users can currently hire AI agents connected to Slack or Teams. This change adds Telegram as a third messaging platform for **both** the Hermes and OpenClaw runtimes. Managed Bots (automated bot creation via Telegram API 9.6) is deferred to a follow-up — this PR implements the token-paste flow only.

**Hermes**: Natively supports Telegram. `hermes gateway run` auto-detects Telegram from config + env vars. Long polling (no public URL needed). Telegram auth handled natively via config fields (`allow_from`, `group_allowed_chats`, `guest_mode`) — no custom plugins needed.

**OpenClaw**: Telegram is built-in (no `@openclaw/telegram` plugin install needed, unlike `@openclaw/slack`). Config uses `channels.telegram` section in the overlay JSON, following the same pattern as `channels.slack` and `channels.msteams`.

**Shared**: DB models, repository, service layer, UI, and bot token validation are runtime-agnostic. aai-cli integration tools work identically (platform-independent pipeline).

**User flow**: paste one bot token from @BotFather → validate via `getMe` API → done. One token, one step.

## Approach: TDD

Each sub-task follows **test-first development**:
1. Write failing tests that define the expected behavior
2. Implement the production code to make tests pass
3. Run `make check-api && make test-api` after each sub-task — zero regressions allowed

Sub-tasks 1-3 were already implemented without tests. They get retroactive test coverage before any new feature code is written.

---

## Sub-task 0: Test Infrastructure — FIRST PRIORITY

Before any tests can run, the shared test utilities must support Telegram.

**Files to modify:**
- `api/tests/steps/agent.py` — add `TEST_TELEGRAM_BOT_TOKEN` constant, add `elif platform == AgentPlatform.TELEGRAM:` branch to `there_is_an_agent()` that creates an `AgentTelegramConfig`
- `api/tests/steps/database.py` — add `agent_telegram_config` to the TRUNCATE statement (line 62)
- `api/tests/steps/agent.py` imports — add `AgentTelegramConfig` import

**Verification:** `make test-api` passes (existing tests still green).

---

## Sub-task 1: DB Models + Migration — COMPLETED (code done, needs tests)

Already implemented: `AgentPlatform.TELEGRAM`, `TelegramGroupPolicy`/`TelegramDmPolicy` enums, `AgentTelegramConfig` table, `AgentTelegramConfigRead`, Telegram fields on `AgentCreate`/`AgentUpdate`, migration `e1f2a3b4c5d6`.

### Tests to write (retroactive)

**File:** `api/tests/unit/test_telegram_models.py` (new)

- `test_agent_create_telegram_requires_bot_token` — `AgentCreate(platform="telegram")` without `telegram_bot_token` raises ValidationError
- `test_agent_create_telegram_accepts_valid_fields` — `AgentCreate(platform="telegram", telegram_bot_token="123:ABC")` passes validation
- `test_agent_create_telegram_rejects_slack_fields` — platform=telegram with `slack_bot_token` set raises (validator rejects cross-platform fields)
- `test_telegram_config_read_from_attributes` — `AgentTelegramConfigRead.model_validate()` round-trips correctly
- `test_telegram_group_policy_enum_values` — OPEN="open", ALLOWLIST="allowlist"
- `test_telegram_dm_policy_enum_values` — OFF="off", OPEN="open", ALLOWLIST="allowlist"

---

## Sub-task 2: Telegram Infrastructure Client — COMPLETED (code done, needs tests)

Already implemented: `api/infrastructure/telegram/client.py` with `validate_bot_token()`, `api/core/config.py` with `skip_telegram_token_validation`.

### Tests to write (retroactive)

**File:** `api/tests/unit/test_telegram_client.py` (new)

Mirror `test_slack_client.py` / `test_slack_transport.py` patterns. Use `unittest.mock.patch("httpx.get", ...)`.

- `test_validate_bot_token_valid` — mock 200 `{"ok": true, "result": {"id": 123, "is_bot": true, "username": "test_bot"}}` → returns `(True, "", {"id": 123, ...})`
- `test_validate_bot_token_invalid` — mock 200 `{"ok": false, "description": "Not Found"}` → returns `(False, "Telegram bot token is invalid: ...", {})`
- `test_validate_bot_token_http_401` — mock 401 → returns `(False, ..., {})`
- `test_validate_bot_token_network_error` — mock raises `httpx.TransportError` → returns `(False, "Could not reach Telegram...", {})`
- `test_validate_bot_token_retries_on_429` — mock 429 then 200 → returns success, verify two calls made
- `test_validate_bot_token_retries_on_transport_error` — mock transport error then 200 → returns success
- `test_validate_bot_token_skip_validation` — with `skip_telegram_token_validation=True` → returns `(True, "", {"username": "skipped"})` without HTTP call

---

## Sub-task 3: Repository + Service Layer — COMPLETED (code done, needs tests)

Already implemented: repository CRUD methods, service create/update/list/get with Telegram support.

### Tests to write (retroactive)

**File:** `api/tests/integration/test_agents.py` (extend existing file)

Follow existing patterns in this file (BDD-style with `given/when/then`, `_GIVEN` setup lists):

- `test_create_telegram_agent_returns_201_stopped` — POST with `platform=telegram`, `telegram_bot_token`, mock token validation → 201 with `telegram_config` in response
- `test_create_telegram_agent_missing_token_returns_422` — POST without `telegram_bot_token` → 422
- `test_create_telegram_agent_invalid_token_returns_400` — mock validation failure → 400
- `test_get_telegram_agent_includes_telegram_config` — GET returns `telegram_config` with policies + bot_username
- `test_list_agents_includes_telegram_config` — GET list returns telegram agents with config
- `test_update_telegram_agent_policies` — PATCH with `telegram_group_policy`, `telegram_dm_policy` → 200 with updated config
- `test_update_telegram_agent_rejects_slack_fields` — PATCH with `slack_bot_token` on a telegram agent → 422
- `test_update_slack_agent_rejects_telegram_fields` — PATCH with `telegram_bot_token` on a slack agent → 422
- `test_update_telegram_agent_token_revalidates` — PATCH with `telegram_bot_token` calls validation, updates `bot_username`

**Note:** These integration tests require mocking `validate_telegram_bot_token` at the service level since the real Telegram API isn't available in tests. Use `unittest.mock.patch("api.domains.agents.service.validate_telegram_bot_token", ...)`.

---

## Sub-task 4: Builders for Telegram (Both Runtimes)

### 4a: Hermes Builders — Tests first, then implement

**Tests file:** `api/tests/unit/test_hermes_builders.py` (extend existing)

Write these tests first (they will fail until the builders are implemented):

- `test_build_hermes_config_telegram_sets_model` — config has correct model fields
- `test_build_hermes_config_telegram_has_no_slack_section` — no `slack` key in config
- `test_build_hermes_config_telegram_has_telegram_platform` — `platforms.telegram.extra` exists
- `test_build_hermes_config_telegram_dm_off_empty_allow_from` — `dm_policy="off"` → `allow_from: []`
- `test_build_hermes_config_telegram_dm_open_wildcard` — `dm_policy="open"` → `allow_from: ["*"]`
- `test_build_hermes_config_telegram_dm_allowlist_passes_ids` — `dm_policy="allowlist"` → `allow_from: [user_ids]`
- `test_build_hermes_config_telegram_group_open_guest_mode` — `group_policy="open"` → `guest_mode: true`, no `group_allowed_chats`
- `test_build_hermes_config_telegram_group_allowlist` — `group_policy="allowlist"` → `guest_mode: false`, `group_allowed_chats: [chat_ids]`
- `test_build_hermes_config_telegram_only_telemetry_plugin` — plugins.enabled == `["telemetry-push"]` (no Slack plugins)
- `test_build_secret_hermes_telegram_contains_required_keys` — `TELEGRAM_BOT_TOKEN`, `AGENT_PLATFORM=telegram`, `OPENAI_API_KEY`, etc.
- `test_build_secret_hermes_telegram_no_slack_keys` — no `SLACK_*` keys
- `test_build_secret_hermes_slack_has_agent_platform` — existing `build_secret_hermes_slack()` includes `AGENT_PLATFORM=slack` (backward compat)
- `test_build_hermes_config_map_telegram_omits_slack_plugins` — when `platform="telegram"`, no `slack-deny-dms-*` or `slack-channel-allowlist-*` keys
- `test_build_hermes_config_map_telegram_has_telemetry_plugin` — telemetry-push files still present
- `test_hermes_start_sh_conditional_slack_plugins` — start.sh uses `if [ -f ... ]` for Slack plugins

**Implementation files:**
- `api/domains/agents/builders/hermes.py` — add `build_hermes_config_telegram()`, `build_secret_hermes_telegram()`, parameterize `build_hermes_config_map()` with `platform`
- `api/domains/agents/builders/__init__.py` — re-export new functions
- `api/domains/agents/scripts/hermes/start.sh` — conditional Slack plugin copying

**Run:** `make test-api` — all new tests pass, all existing tests still pass.

### 4b: OpenClaw Builders — Tests first, then implement

**Tests file:** `api/tests/unit/test_openclaw_builders.py` (extend existing)

- `test_build_openclaw_config_overlay_telegram_has_telegram_channel` — `channels.telegram.enabled == True`
- `test_build_openclaw_config_overlay_telegram_no_slack_channel` — no `channels.slack` key
- `test_build_openclaw_config_overlay_telegram_dm_off` — `dmPolicy="allowlist"`, `allowFrom=[]`
- `test_build_openclaw_config_overlay_telegram_dm_open` — `dmPolicy="open"`, `allowFrom=["*"]`
- `test_build_openclaw_config_overlay_telegram_dm_allowlist` — `dmPolicy="allowlist"`, `allowFrom=[user_ids]`
- `test_build_openclaw_config_overlay_telegram_gateway_auth_none` — `gateway.auth.mode == "none"`
- `test_build_openclaw_config_overlay_telegram_exec_mode_full` — `tools.exec.mode == "full"`
- `test_build_openclaw_config_overlay_telegram_binding_routes_to_telegram` — binding match is `{"channel": "telegram"}`
- `test_build_secret_telegram_contains_required_keys` — `TELEGRAM_BOT_TOKEN`, `LITELLM_API_KEY`, `AGENT_PLATFORM=telegram`
- `test_build_secret_telegram_no_slack_keys` — no `SLACK_*` keys
- `test_build_secret_slack_has_agent_platform` — existing `build_secret_slack()` includes `AGENT_PLATFORM=slack`
- `test_openclaw_start_sh_conditional_slack_install` — start.sh skips `@openclaw/slack` install when platform != slack
- `test_init_openclaw_js_has_telegram_replace_paths` — `REPLACE_PATHS` includes telegram entries
- `test_init_openclaw_js_has_telegram_credential_sync` — credential sync loop handles telegram

**Implementation files:**
- `api/domains/agents/builders/openclaw.py` — add `build_openclaw_config_overlay_telegram()`, `build_secret_telegram()`
- `api/domains/agents/builders/__init__.py` — re-export new functions
- `api/domains/agents/scripts/openclaw/start.sh` — conditional `@openclaw/slack` install
- `api/domains/agents/scripts/openclaw/init-openclaw.js` — add telegram REPLACE_PATHS + credential sync

**Run:** `make test-api` — all new tests pass, all existing tests still pass.

### 4c: Wire in `start_agent()` (service.py)

**Tests:** Add integration tests in `api/tests/integration/test_agents.py`:
- `test_start_telegram_hermes_agent_creates_k8s_resources` — mock K8s, verify config_map + secret + deployment created with Telegram config
- `test_start_telegram_openclaw_agent_creates_k8s_resources` — same for OpenClaw

**Implementation:** Add `elif agent.platform == AgentPlatform.TELEGRAM:` to `start_agent()` in `service.py`, import new builders.

**Run:** `make test-api` — all pass.

---

## Sub-task 5: Platform-Aware Scripts — Tests first, then implement

### 5a: Hermes Scripts

**Tests file:** `api/tests/unit/test_hermes_builders.py` (extend — scripts are read into builder constants)

- `test_hermes_healthz_server_detects_agent_platform` — healthz-server.py source contains `AGENT_PLATFORM` env var reading
- `test_hermes_healthz_server_has_telegram_validation` — source contains telegram `getMe` URL pattern

**Tests file:** `api/tests/unit/test_hermes_telemetry_push_plugin.py` (extend existing)

- `test_telemetry_push_uses_agent_platform_env` — plugin source reads `AGENT_PLATFORM`
- `test_telemetry_push_session_key_uses_platform_var` — session key format uses platform variable, not hardcoded `"slack"`

**Implementation files:**
- `api/domains/agents/scripts/hermes/healthz-server.py` — platform-aware token validation
- `api/domains/agents/scripts/hermes/plugins/telemetry-push/__init__.py` — platform-aware session keys

### 5b: OpenClaw Scripts

**Tests file:** `api/tests/unit/test_openclaw_builders.py` (extend — scripts are read into builder constants)

- `test_openclaw_healthz_server_detects_agent_platform` — healthz-server.js source contains `AGENT_PLATFORM` env reading
- `test_openclaw_healthz_server_has_telegram_validation` — source contains telegram getMe validation logic

**Implementation files:**
- `api/domains/agents/scripts/openclaw/healthz-server.js` — platform-aware token validation

**Run:** `make test-api` after each.

---

## Sub-task 6: Conversation Parsers — Tests first, then implement

**Tests file:** `api/tests/unit/test_conversation_parser.py` (extend existing)

- `test_hermes_distinct_conversations_telegram_dm` — session with key `agent:main:telegram:dm:123` recognized as DM
- `test_hermes_distinct_conversations_telegram_group` — session with key `agent:main:telegram:group:456` recognized as channel
- `test_hermes_channel_sessions_telegram` — Telegram session keys parsed correctly

**Tests file:** `api/tests/unit/test_conversation_parser.py` (extend for OpenClaw parser too)

- `test_openclaw_parser_telegram_session_prefix` — sessions with `agent:main:telegram:channel:` prefix are recognized

**Implementation files:**
- `api/domains/conversations/hermes_parser.py` — add Telegram prefixes
- `api/domains/conversations/parser.py` — add Telegram session prefixes

**Run:** `make test-api`.

---

## Sub-task 7: UI Changes

**Files to modify:**
- `ui/src/features/agents/schemas.ts` — add `"telegram"` to platform enum, add `AgentTelegramConfigSchema`, add `telegramConfig` to `AgentSchema`
- `ui/src/features/agents/components/hire-dialog-steps.tsx` — add `TelegramTokenStep`, add Telegram to `PlatformChoiceStep`
- `ui/src/features/agents/components/hire-dialog.tsx` — add Telegram wizard flow + state + provisioning, re-enable platform picker for both runtimes
- `ui/src/features/agents/components/config-drawer.tsx` — add "Chats" tab for Telegram config
- `ui/src/features/agents/components/agent-meta-badges.tsx` — add Telegram platform badge
- `ui/src/features/agents/hooks/use-create-agent.ts` — add Telegram fields
- `ui/src/features/agents/hooks/use-update-agent.ts` — add Telegram fields

**Files to create:**
- `ui/src/features/agents/components/telegram-config-panel.tsx`
- `ui/public/brand/telegram.svg`

**UI tests** (`ui/tests/`):
- Extend `ui/tests/pages/data-support/agent-data-support.po.ts` with Telegram agent mock data
- Extend `ui/tests/e2e/hire-dialog.spec.ts` with Telegram hire flow test
- Extend `ui/tests/e2e/agent-detail-page.spec.ts` with Telegram config panel test

**Verification:** `make lint-ui && make check-ui` — pass. Playwright tests pass. Manual walkthrough of hire + config flows.

---

## Regression Safety

After each sub-task:
1. `make check-api` — lint + type check pass
2. `make test-api` — all tests pass (unit + integration)
3. Verify no existing Slack/Teams tests broke

At the end:
4. `make lint-ui && make check-ui` — UI clean
5. Full `make test-api` coverage report — Telegram code paths covered
6. Dev server walkthrough (if possible)

---

## Parity Checklist

| Feature | Slack | Telegram (Hermes) | Telegram (OpenClaw) |
|---------|-------|-------------------|---------------------|
| Token validation | `auth.test` + `apps.connections.open` | `getMe` | `getMe` |
| Token storage | `bot_token_encrypted` + `app_token_encrypted` | `bot_token_encrypted` | `bot_token_encrypted` |
| Config table | `agent_slack_config` | `agent_telegram_config` | `agent_telegram_config` |
| Config generation | `build_hermes_config()` | `build_hermes_config_telegram()` | `build_openclaw_config_overlay_telegram()` |
| K8s Secret | `build_secret_hermes_slack()` | `build_secret_hermes_telegram()` | `build_secret_telegram()` |
| Auth enforcement | Hermes: plugins / OC: config overlay | Hermes config native | OpenClaw config overlay |
| Connection mode | Socket Mode (Slack) | Long polling | Built-in (long polling) |
| Plugin install needed | `@openclaw/slack` (OC) | None | None (built-in) |
| Telemetry session keys | `agent:main:slack:*` | `agent:main:telegram:*` | `agent:main:telegram:*` (from ctx.sessionKey) |
| Healthz | Slack tokens every 5m | `getMe` every 5m | `getMe` every 5m |
| aai-cli / skills | Works | Works (same pipeline) | Works (same pipeline) |

---

## Verification

1. `make check-api` + `make test-api` — all pass after every sub-task
2. `make lint-ui` + `pnpm tsc --noEmit` — all pass
3. Dev server walkthrough:
   - Hire a **Hermes** agent → platform picker shows Slack + Telegram → choose Telegram → paste token → hire
   - Hire an **OpenClaw** agent → platform picker shows Slack + Telegram → choose Telegram → paste token → hire
   - Verify ConfigMap: Hermes has `platforms.telegram.extra`, OpenClaw has `channels.telegram` in overlay
   - Verify Secret: `TELEGRAM_BOT_TOKEN` present, no `SLACK_*` vars
   - Start agent, verify healthz validates Telegram token via `getMe`
   - Config drawer → "Chats" tab shows policies and ID lists
   - Update policies → save → restart → verify new config applied
   - Assign integrations (GitHub, etc.) → verify aai-cli works
