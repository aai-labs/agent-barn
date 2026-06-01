# AF-108 Hermes Agents Support — Implementation Notes

## Overview

Added a second agent runtime (Hermes, `nousresearch/hermes-agent`) alongside OpenClaw.
Users can choose between `openclaw` and `hermes` at agent creation time.
Hermes is Slack-only for v1.

---

## Database / Models

### Migration: `api/migrations/versions/c1d2e3f4a5b6_add_agent_type_to_agent.py`
- Adds `agent_type VARCHAR(20) NOT NULL DEFAULT 'openclaw'` to the `agent` table.
- Check constraint: `agent_type IN ('openclaw', 'hermes')`.
- `server_default='openclaw'` ensures existing rows backfill without a data migration.

### `api/domains/agents/models.py`
- Added `AgentType(str, enum.Enum)` with values `OPENCLAW = "openclaw"` and `HERMES = "hermes"`.
- Added `agent_type: AgentType` column on the `Agent` SQLModel table.
- Added `agent_type: AgentType = AgentType.OPENCLAW` field on `AgentCreate`.
- Extended `AgentCreate.validate_platform_credentials` to raise 422 for `hermes + teams` (Hermes is Slack-only).
- Added `agent_type: AgentType` to `AgentRead` so callers can see which runtime is in use.

---

## Config & Helm

### `api/core/config.py`
- Added `hermes_image: str = ""` field — the fully-qualified image ref for the Hermes container, controlled via env var `HERMES_IMAGE`.

### `helm/agentfarm-api/values.yaml`
- Added `hermesImage.repository` / `hermesImage.tag` following the same pattern as `openclawImage`.

### `helm/agentfarm-api/templates/deployment.yaml`
- Added `HERMES_IMAGE` env var wired from `hermesImage.repository:hermesImage.tag`.

---

## Builders package

Previously a single `builders.py` (~1000 lines). Split into a package to keep OpenClaw and Hermes logic separate and navigable.

### `api/domains/agents/builders/common.py`
Shared k8s helpers used by both runtimes:
- `_resource_name(agent_id)` — returns `"agent-{id}"`
- `_labels(agent_id, org_id)` — standard pod labels
- `build_pvc(...)` — 1Gi ReadWriteOnce PVC (same for both runtimes)
- `build_service(...)` — ports 80 (gateway), 8081 (healthz), optionally 3978 (Teams webhook)

### `api/domains/agents/builders/openclaw.py`
All OpenClaw-specific logic. Loads scripts from `scripts/openclaw/` at import time via `Path(__file__).parent.parent / "scripts" / "openclaw"`.

Constants (loaded from files):
- `INIT_OPENCLAW_JS` — merges the config overlay into `openclaw.json` at startup, restores preinstalled Teams npm plugin when needed, syncs allowFrom credentials files.
- `HEALTHZ_SERVER_JS` — polls `openclaw health --json`, exposes `/ready` and `/healthz` on :8081.
- `START_SH` — runs healthz sidecar, runs init script, execs `openclaw gateway --allow-unconfigured`.

Functions:
- `build_openclaw_config_overlay(...)` — builds the JSON overlay for Slack agents (model, channel list, DM policy, plugins).
- `build_openclaw_config_overlay_teams(...)` — builds the JSON overlay for Teams agents.
- `build_config_map(...)` — ConfigMap containing all 8 template MD files + overlay + scripts.
- `build_secret_slack(...)` — Secret with `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `LITELLM_API_KEY`, `LITELLM_BASE_URL`.
- `build_secret_teams(...)` — Secret with Teams credentials + LiteLLM keys.
- `build_deployment(...)` — Deployment; mounts `config` ConfigMap → `/app/config`, `data` PVC → `/home/node/.openclaw`.

### `api/domains/agents/builders/hermes.py`
All Hermes-specific logic. Loads scripts from `scripts/hermes/` at import time.

Constants (loaded from files):
- `HERMES_BOOTLOADER_FOOTER` — markdown footer appended to SOUL.md; tells the agent where the other personality files live on disk (`/workspace/IDENTITY.md`, etc.). Needed because Hermes only natively reads SOUL.md into its system prompt; other files are lazy-loaded via terminal tools.
- `HERMES_HEALTHZ_PY` — Python sidecar that polls `GET /v1/models` with `Bearer $API_SERVER_KEY` on port 8642, exposes `/ready` and `/healthz` on :8081. Uses Bearer auth because Hermes's API server is protected unlike OpenClaw's health endpoint.
- `HERMES_START_SH` — seeds USER.md once to PVC (seed-once semantics for user memory persistence), copies SOUL.md and config.yaml, drops both plugins, copies workspace files, execs `hermes gateway run`.
- `SLACK_DENY_DMS_PLUGIN_YAML` / `SLACK_DENY_DMS_PLUGIN_INIT` — plugin that denies all Slack DMs unless the sender is in `SLACK_DM_ALLOWED_USERS`. Ported from ocbw; consolidated with the allowlist logic into one plugin to avoid hook ordering problems (you can't have one plugin's `skip` overridden by another plugin's `allow`).
- `SLACK_CHANNEL_ALLOWLIST_PLUGIN_YAML` / `SLACK_CHANNEL_ALLOWLIST_PLUGIN_INIT` — plugin that restricts responses to channels listed in `SLACK_CHANNEL_IDS`. If `SLACK_CHANNEL_IDS` is empty, the agent responds in all channels (mirrors OpenClaw `groupPolicy: open`). DMs are ignored by this plugin; they are handled by `slack-deny-dms`.

Functions:
- `build_hermes_config(model, litellm_base_url)` — builds the Hermes YAML config dict. Key settings: `unauthorized_dm_behavior: ignore` (plugins handle DM auth, not Hermes native pairing), `plugins.enabled: ["slack-channel-allowlist", "slack-deny-dms"]` (channel filter runs first).
- `build_hermes_config_map(...)` — ConfigMap with all template MD files (no `BOOTSTRAP.md` — OpenClaw-specific), SOUL.md with bootloader footer appended, `hermes-config.yaml`, both plugin files, `healthz-server.py`, `start.sh`.
- `build_secret_hermes_slack(...)` — Secret with Slack tokens, LiteLLM keys mapped to `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENROUTER_BASE_URL` (Hermes expects OpenAI-compatible env vars), `API_SERVER_KEY` (generated fresh per start — not persisted), `SLACK_CHANNEL_IDS`, `SLACK_DM_ALLOWED_USERS`, `SLACK_ALLOW_ALL_USERS=true` (channels are open; plugins handle filtering), `GATEWAY_ALLOW_ALL_USERS=true`.
- `build_hermes_deployment(...)` — Deployment; mounts `config` ConfigMap → `/app/config`, `data` PVC → `/opt/data`, `workspace` emptyDir → `/workspace`. The workspace is ephemeral (emptyDir) because Hermes writes working files there per session; only `/opt/data` (PVC) is persistent.

### `api/domains/agents/builders/__init__.py`
Re-exports everything from the three submodules so all existing imports (`from api.domains.agents.builders import ...`) continue to work without change.

---

## Scripts directory

Previously the pod scripts were inline Python string constants. Moved to actual files so they get IDE syntax highlighting, linting, and clean diffs.

```
api/domains/agents/scripts/
├── openclaw/
│   ├── init-openclaw.js
│   ├── healthz-server.js
│   └── start.sh
└── hermes/
    ├── healthz-server.py
    ├── start.sh
    ├── bootloader-footer.md
    └── plugins/
        ├── slack-deny-dms/
        │   ├── plugin.yaml
        │   └── __init__.py
        └── slack-channel-allowlist/
            ├── plugin.yaml
            └── __init__.py
```

Each builder module loads its scripts with `Path(__file__).parent.parent / "scripts" / "<runtime>"` at import time. The loaded strings are exposed as module-level constants for backward compatibility and testability.

---

## Service layer

### `api/domains/agents/service.py`

**`create_agent`**: stores `agent_type=data.agent_type` on the Agent row.

**`start_agent`**: the SLACK platform branch now sub-branches on `agent.agent_type`:

- `AgentType.HERMES`: generates a fresh `api_server_key` via `secrets.token_urlsafe(32)` (not stored in DB — regenerated on every start so a leaked key is invalidated on the next restart), calls `build_hermes_config`, `build_hermes_config_map`, `build_secret_hermes_slack`, `build_hermes_deployment`.
- `AgentType.OPENCLAW` (default): existing path unchanged.

The Teams branch was also refactored to use local `config_map` / `deployment` variables (same pattern as the Slack branch) so the k8s call block at the bottom is unified.

**`pair_agent`**: explicitly rejects Hermes agents with 400 before the general platform check. Pairing is an OpenClaw-specific feature.

**`start_agent` error handling**: added `logger.exception(...)` to the catch block so k8s failures produce a traceback in the API pod logs instead of silently becoming a generic 500.

---

## Defaults

### `api/domains/agents/defaults.py`
Replaced minimal placeholder strings with the richer content ported from the ocbw `profiles/default/` directory (Jinja template variables stripped). Affects `DEFAULT_AGENTS_MD`, `DEFAULT_TOOLS_MD`, `DEFAULT_USER_MD`, `DEFAULT_BOOT_MD`, `DEFAULT_HEARTBEAT_MD`.

---

## UI

### `ui/src/features/agents/schemas.ts`
Added `agentType: z.enum(["openclaw", "hermes"]).default("openclaw")` to `AgentSchema` so the API response is correctly typed.

### `ui/src/features/agents/hooks/use-create-agent.ts`
Added `agentType?: "openclaw" | "hermes"` to `CreateAgentData`.

### `ui/src/features/agents/components/hire-dialog-steps.tsx`
Added `agentType` + `onAgentTypeChange` props to `DetailsStep`. Added a "Agent runtime" `<select>` (OpenClaw / Hermes) visible only when `platform === "slack"` (Hermes is Slack-only, so Teams flow never shows it).

### `ui/src/features/agents/components/hire-dialog.tsx`
Added `agentType` state defaulting to `"openclaw"`. Passes `agentType: platform === "slack" ? agentType : "openclaw"` into `createAgent.mutateAsync` (Teams always gets openclaw).

---

## Tests

### New: `api/tests/unit/test_hermes_builders.py`
Unit tests for all Hermes builder functions and constants:
- `build_hermes_config`: model parsing, `unauthorized_dm_behavior`, plugin list.
- `build_hermes_config_map`: required keys, SOUL.md bootloader footer, no BOOTSTRAP.md, valid YAML.
- `build_secret_hermes_slack`: all required env vars, `SLACK_CHANNEL_IDS`, `SLACK_DM_ALLOWED_USERS`, empty-list edge cases.
- `HERMES_START_SH`: contains `hermes gateway run`, seeds USER.md, copies channel-allowlist plugin.
- Plugin `__init__.py` files: `compile()` to verify syntax.
- `build_hermes_deployment`: volume mounts and emptyDir workspace.

### Updated: `api/tests/integration/test_agents.py`
New Hermes integration tests:
- **Happy paths**: create hermes+slack (201 stopped), agent_type defaults to openclaw, start with hermes image (RUNNING + k8s calls verified), configmap has hermes-config.yaml + both plugins + bootloader footer in SOUL.md, secret has SLACK_CHANNEL_IDS + SLACK_DM_ALLOWED_USERS, deployment mounts /opt/data and /workspace with emptyDir.
- **Validation**: hermes+teams → 422, missing slack tokens → 422.
- **Pair**: hermes agent → 400.
- **Slack API**: list channels works for hermes agents (uses same bot token flow).
- **Migration**: `test_existing_agent_rows_backfill_to_openclaw` — reads an agent row and asserts `agent_type == AgentType.OPENCLAW` (verifies the `server_default` is applied).

### Updated: `api/tests/steps/agent.py`
Added `agent_type: AgentType = AgentType.OPENCLAW` parameter to `there_is_an_agent` fixture.

---

## Key design decisions

**Why one DM plugin instead of two**: The original plan called for `slack-deny-dms` (deny all) + `slack-dm-allowlist` (allow specific users). Two plugins can't cleanly interact because Hermes hook processing does not support an `allow` action that overrides a later `skip`. Combining both behaviors into one `slack-deny-dms` plugin (deny all DMs except users in `SLACK_DM_ALLOWED_USERS`) is the only correct approach.

**Why `slack-channel-allowlist` is a separate plugin from `slack-deny-dms`**: They filter different dimensions (channel vs DM), have no interaction with each other, and separation keeps each plugin's logic simple and single-purpose. Channel-allowlist runs first in `plugins.enabled`; if it skips (non-allowed channel), deny-dms never runs. For DMs, channel-allowlist passes (it ignores DMs), then deny-dms handles them.

**Why `API_SERVER_KEY` is generated fresh per start**: If the key were stored in the DB, a leaked key would remain valid until the agent was deleted. Regenerating on start means stopping and restarting the agent invalidates any leaked key. The key only needs to live for the duration of one running session.

**Why `SOUL.md` gets a bootloader footer injected**: Hermes natively reads only `SOUL.md` into its system prompt slot. The other personality files (`IDENTITY.md`, `AGENTS.md`, etc.) are on disk but not auto-loaded. The footer instructs the agent where to find them so it can lazy-load via terminal tools. Concatenating everything into SOUL.md was rejected because it risks truncation for large configs and conflicts with Hermes's agent-mutable memory model.

**Why `workspace` is emptyDir**: The workspace (`/workspace`) is where Hermes writes session artifacts and runs terminal commands. It should be empty on each pod start (fresh session). Only `/opt/data` (PVC) is persistent across restarts — it holds `SOUL.md`, `config.yaml`, plugins, and the seed `USER.md`.

**Why USER.md is seeded once**: `start.sh` only copies USER.md to the PVC if it doesn't already exist (`[ ! -f /opt/data/memories/USER.md ]`). This preserves any user-profile updates the agent has written to the file across restarts, while still providing the default content on first start.
