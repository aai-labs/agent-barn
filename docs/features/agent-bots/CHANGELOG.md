# Agent Bots — change log

Status: Active
Epic: AF-425
Related context: [`../agent-bots.md`](../agent-bots.md), [`../../adr/2026-11-05-bots-share-their-parent-agents-gateway.md`](../../adr/2026-11-05-bots-share-their-parent-agents-gateway.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: terminology, the feature contract, the ADR, the schema (`agent.parent_agent_id`, `agent.bot_slot` and the database rules), and the API's reading of Bots:
  - `pod_agent_id`;
  - a Bot's lifecycle lock is its Parent Agent's;
  - Bots are left out of Agent lists and the pod-based platform queries;
  - a Bot inherits its Parent Agent's access;
  - the sharing floor;
  - `GET /agents/{id}/bots`;
  - `POST /agents/{id}/bots`.
  Starting a Parent Agent now serves its Bots from its pod. Not yet verified in a real pod.
- In transition: nothing.
- Next: the full end-to-end run in local k3d on a fresh API image.
- Accepted: a Bot's scheduled-job history stays in the Parent Agent's `state.db`, because Hermes opens that database itself; keeping it per Bot would need a Hermes patch.
- Blockers: none.

## Runtime evidence

From a spike on 2026-11-06 against Hermes `v2026.8.19` in local k3d: a real Parent Agent and two real Bots, created through the API, served by one pod. Later slices may rely on these.

**Observed working:**
- One gateway served the Parent Agent and two Bots, each on its own model and its own LiteLLM key, with spend recorded per key.
- Two Slack apps and three Telegram bots connected in the one process, each replying as itself, with no duplicate-credential error. Each Bot's sessions stayed in its own profile.
- Web Chat reached each Bot through its own communications adapter calling `/p/<bot-id>`.
- With `terminal.env_passthrough`, each Bot's terminal saw only its own values, under concurrent runs and in `execute_code`, background commands, subagents and scheduled jobs. An `export` in one Bot didn't reach another. A Bot's artifact key acted as that Bot, and each Bot's `aai-cli` read its own config.
- A Bot's trigger server on its own port accepted that Bot's key only and created the job in that Bot's store.
- A spend limit on one Bot stopped only that Bot.
- After a restart, a Bot's runtime keys rotated and it kept working. The LiteLLM key was the same before and after.
- The pod started with one Bot's Secret missing; the Parent Agent and the other Bot kept working.

**Observed behaviour that shapes the design:**
- `/workspace/AGENTS.md` reaches every profile's prompt; each Bot's instructions must live in its own profile.
- A Bot whose Secret was missing still started its adapter and trigger server, which took the Parent Agent's identity from the process environment.
- `telemetry-push` read its identity from the process environment, so every Bot's tool calls were filed under the Parent Agent. Reading it from the profile's own `.env` filed them correctly.
- The LLM error marker is one shared file, so one Bot's spend limit showed as the pod's error.
- When the Parent Agent and a Bot both had Telegram, the Bot's scheduled message went through the Parent Agent's Telegram adapter. With the Parent Agent off that platform, scheduled messages on Slack and Telegram came from the Bot's own account.
- The trigger server only accepts a platform delivery, so a Bot's webhooks rely on that delivery path.
- Bots' scheduled-job sessions were stored in the Parent Agent's `state.db`, and their tool calls didn't reach Ingest.

**Measured:**
- Idle memory: Parent Agent with two Bots in one pod, 310 MiB; the same three as separate Agents, about 290 MiB each.
- Per Bot: about 25 MB for its communications adapter and 25–28 MB for its trigger server.
- A Bot's prompt was about 23,000 characters, with no truncation.

**Not covered:** Slack access rules across two homes (the local image predates the plugin), Discord, and memory under 10 concurrent runs.

## Changes

### 2026-11-09 — AF-425 — Bot rules on template selection and restore

- Fixed: selecting a Template now applies the Bot rules for approval mode and the turn limit, as editing an Agent does. A Parent Agent's selection and a Restore Point's recorded configuration now pass those settings to its Bots.

### 2026-11-09 — AF-425 — Discord on Bots

- Delivered: a Bot can connect its own Discord bot. Its token and access lists reach its `.env`, and its mention setting is written to `platforms.discord.extra`, which Hermes reads before the process environment.
- Accepted: Discord settings Agent Barn doesn't set, such as auto-threading and reactions, are process-wide in Hermes `v2026.8.19`, so every Bot uses the same defaults.
- Not yet verified: a real Discord connection on a Bot.

### 2026-11-09 — AF-425 — Parent Agents and Bots on the same platform

- Delivered: `hermes-base/patch-bot-cron-delivery.py`, so a Bot's scheduled jobs use the Bot's own connections and a Bot never falls back to its Parent Agent's. A Parent Agent and its Bots can now connect the same platform, with their own apps.
- Changed: only Agent Barn Telegram on a Parent Agent with a Bot's own Telegram is refused. `docs/architecture/runtime-and-deployment.md`, the feature contract, and a new ADR.
- Observed: in local k3d on Slack, a Parent Agent and a Bot each replied and delivered a scheduled job through their own connection. Telegram, a Bot's job while its connection is down, separate Slack access rules and a restart are still to verify in the end-to-end run.

### 2026-11-09 — AF-425 — Bot connection status

- Fixed: a Bot's Provider connectivity stayed on Pending. The observer now reads the Bot's own entries in the Parent Agent's `gateway_state.json`.
- Delivered: `hermes-base/patch-bot-connected-status.py`, because Hermes `v2026.8.19` records a Bot's platform when it fails but not when it connects or reconnects. The maintainer accepted this one patch on 2026-11-09. It fails the image build if the Hermes source changes.
- Changed: `docs/architecture/runtime-and-deployment.md`.

### 2026-11-09 — AF-425 — Bot sharing and trust warning

- Delivered: the Share dialog on a Bot marks Members who cannot open the Parent Agent as not addable, and offers General access only when the Parent Agent has it. The server still decides when the person sharing cannot manage the Parent Agent's access. The New bot dialog, the Bot switcher and a Bot's Share dialog say that Bots in one Agent can read each other's credentials.
- Follow-up: the full end-to-end run.

### 2026-11-09 — AF-425 — Bot pages and pod-wide controls

- Delivered: a Bot's page shows its own sections. An "Agent" group on Hermes Agents holds Logs, File sync, Resource usage, Restore points and Size, and links to the Parent Agent. Lifecycle actions and Apply & Restart on a Bot act on the Parent Agent and need `agent.lifecycle.manage` there. Bot settings leave out Restore points, Size and the turn limit editor. The switcher shows whether the pod is serving each Bot, and Home shows each Parent Agent's Bot count and how many Bots are in error.
- Changed: `docs/architecture/ui.md`.
- Follow-up: the access floor and the shared-trust warning.

### 2026-11-09 — AF-425 — Bot switcher and New bot dialog

- Delivered: a Bot step in the path bar on Hermes Agents, listing the Parent Agent as main and its Bots, and keeping the current tab when switching. On a Bot, the Agent step shows the Parent Agent. A New bot dialog, offered with `agent.update` on the Parent Agent and disabled at five Bots, with Add & Restart when the Parent Agent is running.
- Changed: `AgentSchema` reads `parent_agent_id`; `docs/architecture/ui.md`.
- Follow-up: Bot-scoped tabs, pod-wide pages and the shared-trust warning.

### 2026-11-09 — AF-425 — Image-level Bot checks

- Delivered: `hermes_bots_driver.py` runs on the real Hermes image in `test-image.sh`: Bot ids as profile names, per-profile terminal passthrough, the Slack gate and plugin, the shared-platform capture, and a Bot's scheduled delivery using its own credential.
- Changed: the Hermes CI path filter and `docs/guidelines/testing.md`.
- Follow-up: UI.

### 2026-11-09 — AF-425 — Bot health

- Delivered: `/healthz` lists the Bots the pod is serving. A Bot reports its pod's health when served, an error naming the fix when it isn't, and initializing until the pod has a list.
- Changed: the runtime digest moves.
- Follow-up: image-level test.

### 2026-11-09 — AF-425 — Restore Point exclusions for Bots

- Delivered: a Parent Agent's capture leaves out each Bot's `.env`, aai-cli store, generated instructions, config, plugins and skills, and keeps its sessions, memory and scheduled jobs. Leftover `.env_*` temp files are left out too.
- Changed: the runtime digest moves.
- Follow-up: Bot health.

### 2026-11-09 — AF-425 — Connection and settings rules

- Delivered:
  - Discord, Teams and Agent Barn Telegram are refused on a Bot (400). A Parent Agent and its Bots cannot share a platform family (409); Bots can share one with each other.
  - Manual approval is all or none: a Bot cannot cross the line alone, and changing a Parent Agent across it moves its Bots too.
  - A Bot's turn limit is read-only and follows its Parent Agent.
  - Each Bot has its own `GOG_HOME`, shares one `gog` shim on the PATH, and the shim hands over to the real binary in a pod with Bots when there is no gateway token.
- Changed: the runtime digest moves.
- Follow-up: Restore Points. Restoring a Parent Agent's recorded configuration does not yet re-apply these rules to its Bots.

### 2026-11-09 — AF-425 — Bot trigger routing

- Delivered: `trigger_target` gives an Agent its own Service on port 8082, and a Bot its Parent Agent's Service on `8100 + slot`. Webhook dispatch and workflow steps use it.
- Changed: `agent_trigger_url` takes `{port}`.
- Follow-up: Connection rules.

### 2026-11-09 — AF-425 — Per-Bot plugin identity

- Delivered: telemetry and the observer report as their own home's Agent, read from that home's `.env`. The Slack access gate no longer falls through to process env. The LLM error marker is keyed per caller under multiplex. A cluster failure creating one Bot's Secret or ConfigMap fails only that Bot.
- Changed: the runtime digest moves.
- Follow-up: pod and port URLs.

### 2026-11-09 — AF-425 — Start and stop with Bots

- Delivered:
  - Starting a Parent Agent assembles each live Bot's own Secret and ConfigMap with fresh runtime keys, mounts them, and ships `bots.json` with the terminal passthrough names; the LiteLLM key is kept.
  - A Bot that fails to assemble goes to ERROR alone and is not served. A line break in any value refuses the start, naming only the key.
  - Bots mirror RUNNING and STOPPED. Stopping removes their Secrets and ConfigMaps, including deleted Bots', and revokes their gateway tokens.
  - Bots report no update and no pending size.
- Changed: `bot-setup.py` writes the passthrough names into every profile and points the aai-cli setup at the Bot's own files. The runtime digest moves.
- Follow-up: per-Bot plugin identity.

### 2026-11-09 — AF-425 — Bot boot step

- Delivered: `bot-setup.py` lays out each Bot as a Hermes profile with its own instructions, paths, skills, plugins and in-memory `.env`, moves the Parent Agent's instructions into its SOUL, syncs approvals, and removes deleted Bots. `bot-run.py` starts each Bot's helpers with only that Bot's environment and refuses a Bot that is not served. A Bot with a missing or mismatched Secret is not served and never takes the Parent Agent's identity. Inert until a start ships `bots.json`.
- Changed: `start.sh`, `boot-run.py` honours `BOOT_FILE`, `build_hermes_config_map(bots_manifest=...)`. The runtime digest moves.
- Follow-up: start and stop.

### 2026-11-09 — AF-425 — Bot builders

- Delivered: builders can mount Bots into a Parent Agent's pod: multiplex, an in-memory `.env` volume, each Bot's optional Secret and ConfigMap, a trigger port per slot, terminal passthrough names with placeholders, and a Bot profile config carrying Slack and Telegram settings in `extra`. Nothing calls them with Bots yet.
- Changed: the runtime digest moves.
- Follow-up: boot step.

### 2026-11-09 — AF-425 — Extract Agent assembly

- Delivered: `_assemble_agent` builds an Agent's Secret, ConfigMap, Deployment and Service. No behaviour change: Hermes and OpenClaw start resources compared byte-for-byte equal before and after.
- Changed: the runtime digest moves, so running Agents report an available update.
- Follow-up: Bot builders.

### 2026-11-09 — AF-425 — Pod operations on a Bot

- Delivered:
  - Start, stop, managed update, Agent Size, Restore Point create, restore and delete, logs, diagnostics, resource usage, File Sync and the platform size and restart routes return 409 on a Bot, naming its Parent Agent.
  - Health, integration readiness, and isolation and Custom API changes use the Parent Agent's pod, guards and `agent.lifecycle.manage`.
  - Deleting a Bot soft-deletes it, retires its Connections and blocks its key without touching the pod. Deleting a Parent Agent also deletes its Bots.
- Changed: `refuse_on_bot`, `AgentService.pod_of`, `AgentRepository.find_live_bots`.
- Follow-up: start path extraction.

### 2026-11-09 — AF-425 — Create a Bot

- Delivered: `POST /agents/{id}/bots`, through the normal Agent create path.
  - Needs `agent.create` in the Organization and `agent.update` on the Parent Agent; the creator owns the new Bot.
  - The Bot is Hermes, stopped, with File Sync off and the Parent Agent's turn limit, in the lowest free slot.
  - Counts toward the Organization's Agent limit.
  - 400 for an OpenClaw parent. 409 for a Bot as parent, a sixth Bot, a running parent, a managed update, a restore operation, or a parent mid-lifecycle.
- Changed: `AgentCreate` now shares a base, `AgentDefinition`, with `BotCreate`. `operations-v1.json` gains the route.
- Follow-up: pod operations on a Bot.

### 2026-11-07 — AF-425 — Bot visibility and access

- Delivered:
  - `pod_agent_id(agent)`;
  - `lifecycle_lock` locks the Parent Agent for a Bot;
  - `GET /agents/{id}/bots` lists visible Bots in slot order;
  - `AgentRead.parent_agent_id`;
  - Agent lists, `find_all_running` and `find_live_for_platform_usage` return Parent Agents only, and Bots stay reachable by id;
  - Agent Access and General Access on a Parent Agent reach its Bots, and Bot grants only add;
  - sharing a Bot with a Member who can't read the Parent Agent, or giving a Bot General Access while its Parent Agent has none, returns 409.
- Changed: `operations-v1.json` gains the Bots route.
- Follow-up: Bot creation. The Platform Agents page and environment health still list Bots, until that product detail is decided.

### 2026-11-06 — AF-425 — Bot schema

- Delivered: migration `e5b81c3d9a27`.
  - `parent_agent_id` uses a composite foreign key to `agent(id, organization_id)` with `ON DELETE CASCADE`.
  - `bot_slot` is set exactly when there is a parent, ranges 1–5, and is unique per Parent Agent among live Agents.
  - Trigger `trg_agent_bot_parent` refuses a changed parent link, a Bot of a Bot, and a non-Hermes Parent Agent or Bot.
- Changed: `Agent` model gains `parent_agent_id` and `bot_slot`.
- Follow-up: resolver, visibility and access.

### 2026-11-06 — AF-425 — Bots documentation

- Delivered: the Bot and Parent Agent terms, the feature contract, the ADR, this log, and the RBAC brief's Bot rules.
- Changed: docs only.
- Follow-up: schema.

### 2026-11-06 — AF-425 — Remove Personas

- Delivered: the Persona implementation removed; files restored to `8113eccf`.
- Changed: Alembic head back to `3680352c132d`; the `personas_enabled` setting removed.
- Follow-up: Bots documentation.
