# Agent Bots — change log

Status: Active
Epic: AF-425 (Hermes), AF-445 (OpenClaw)
Related context: [`../agent-bots.md`](../agent-bots.md), [`../../adr/2026-11-05-bots-share-their-parent-agents-gateway.md`](../../adr/2026-11-05-bots-share-their-parent-agents-gateway.md), [`../../adr/2026-11-11-openclaw-bots-are-agents-in-the-parent-gateway.md`](../../adr/2026-11-11-openclaw-bots-are-agents-in-the-parent-gateway.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

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
- OpenClaw (AF-445): the feature contract, terminology and ADR, the database rule that a Parent Agent and its Bots share a runtime (`865ce7d7db04`), and `POST /agents/{id}/bots` on OpenClaw Parent Agents with the OpenClaw Bot rules, and starting an OpenClaw Parent Agent serves its Bots from its pod. Not yet verified in a real pod.
- In transition: OpenClaw Tasks and listen-in act as the Parent Agent for every Bot until the two slices named in the AF-425 merge entry land.
- Next: OpenClaw Tasks per agent, then OpenClaw listen-in per agent. Then the end-to-end runs in local k3d: Hermes on a fresh API image, including the staging merge's per-Bot work (transcripts, Tasks, listen-in and the organization Tasks page); OpenClaw with real Slack, Telegram and Discord apps.
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

## OpenClaw runtime evidence

From a spike on 2026-11-11 against OpenClaw `2026.8.2` in local k3d: a real OpenClaw Parent Agent and two Bots, created through the API, served as three agents by one gateway with a hand-built configuration. Later slices may rely on these.

**Observed working:**
- `openclaw config validate` accepted `agents.ownership: "explicit"`, `main` plus two Bot entries, and per-Bot workspace, agent directory and model. Each agent answered through `openclaw/<id>`, and its commands ran in its own workspace.
- One model provider per Bot, `litellm-bot-<slot>`, with a file secret reference: a Bot's call was billed to its own LiteLLM key only.
- A `before_tool_call` plugin on `exec` at priority -1000 gave each agent its own `AGENT_ID` and artifact key, in foreground and background commands. A model-supplied `env` could not override them, and a test value never appeared in sessions, state, logs or the `tool_call` table.
- Two Slack apps, two Telegram bots and two Discord bots, as `default` and Bot accounts in one gateway, each replied as itself, and each conversation landed in its own agent's sessions.
- A scheduled job created with `--agent <bot>` ran as that Bot. On Telegram, the Bot's jobs, pinned to its account or not, posted from the Bot's account, and the Parent Agent's from `default`.
- `openclaw channels status --probe --json` reported each account's connection.
- With one Bot's Secret missing, that Bot failed closed with no fallback key; the Parent Agent and the other Bot kept working.
- A Parent Agent's sessions continued as `agent:main:…` after Bots were added, and with its old key after the last Bot was removed.

**Observed behaviour that shapes the design:**
- `openclaw/default` fails once there are several agents, so a Parent Agent with Bots is reached as `openclaw/main`.
- Session keys without an agent prefix fail with several agents; they must be `agent:<id>:…`.
- The file secret provider refuses a symlink, and Secret volume files are symlinks, so Bot keys are copied at boot into private files.
- `init-openclaw.js` merges into the volume's `openclaw.json`, so removing the last Bot left multi-agent settings that broke `openclaw/default` until they were deleted.
- Every tool call was filed under the Parent Agent, because `telemetry-push` reads one `AGENT_ID`.
- Agent Barn's `agentbarn-tasks` plugin, on staging and not on this branch, shows the Parent Agent's Tasks to every agent in the pod. It needs per-Bot identity on both runtimes.

**Measured:** Parent Agent with two Bots, 578 MiB during a scheduled run and 890 MiB idle later, with six platform accounts connected.

**Not covered:** Hindsight session exclusion and the memory tool per Bot, the exec plugin failing closed, compaction and utility-model billing, the Parent Agent's job on a platform only a Bot uses, and five Bots.

## Changes

### 2026-11-13 — AF-445 — AF-425 merge (Agent Tasks, listen-in, workflow approvals)

- Merged: `AF-425-hermes-multi-persona-feat` through `11ce0477`, bringing staging's Agent Tasks, OpenClaw and Hermes listen-in and workflow approvals, and the Hermes Bot work on top of them.
- Changed: the conflicted files keep both sides. Migration `d3c8e1f4a2b7` joins this branch's `865ce7d7db04` with AF-425's `ed009c1e7a7c`.
- Known gaps, from staging's OpenClaw plugins assuming one agent per gateway:
  - `agentbarn-tasks` runs `agentbarn-task` with the Parent Agent's identity and workspace and caches one open-Tasks list for the pod, so a Bot records its work as the Parent Agent and is shown the Parent Agent's Tasks;
  - the `agentbarn-listen-in` guard is loaded only when the Parent Agent has listen-in rooms, reads Slack history only for the Parent Agent's rooms and with its app, and Discord auto-threads stop only on the account that has the rooms.
- Follow-up: OpenClaw Tasks per agent, then OpenClaw listen-in per agent.

### 2026-11-13 — AF-425 — Listen-in test type checking

- Fixed: the listen-in test adapter declares its nullable owner profile, so the per-Bot ingress test passes type checking. Runtime behavior is unchanged.

### 2026-11-13 — AF-425 — Bots on the organization Tasks page

- Delivered: `GET /organizations/{organization_id}/agents` takes `include_bots` (default false). With it, the list also returns the Bots the caller can read, through the same visibility rule, so a Bot readable only through its Parent Agent's grants is included. The Organization Tasks page asks for it: Bots appear in the Agent filter right after their Parent Agent as "Bot · Parent Agent", their Tasks show that name, and the Task dialog links to the Bot.
- Changed: no other caller passes `include_bots`, so Home, Agent lists, onboarding and resource usage still leave Bots out. `operations-v1.json` is unchanged because it lists no query parameters.
- Follow-up: the end-to-end run.

### 2026-11-13 — AF-425 — Listen-in per Bot

- Delivered:
  - `bot-setup.py` copies `agentbarn-listen-in` into each Bot profile and, when the Bot's config enables it, runs `listen-in-check.py` on that profile's `config.yaml`.
  - The guard works out its profile from its install path. It reads that profile's rooms (a Bot's own `config.yaml`, the Parent Agent's `HERMES_HOME`), classifies only messages that belong to its profile, keys them in its own session namespace without changing the message, posts and reads Slack history through its own adapters (`_profile_adapters`), and never treats another profile's session as a room session.
  - `bot_gateway_config` always sets a Bot's `free_response_channels` / `free_response_chats` in its platform settings, empty when it has none.
  - `listen-in-check.py` empties a Bot's own room list when the guard fails to load, instead of removing it.
- Found while checking the pinned Hermes source: its Slack adapter falls back to the process-wide `SLACK_FREE_RESPONSE_CHANNELS`, which the Parent Agent's listen-in config sets, when a profile's own setting is missing. So before this change a Bot's Slack app could take the Parent Agent's listen-in channels as its own free-response rooms, with no guard, wherever it was also allowed in.
- Changed: `ci.yml` selects the Hermes image workflow for `hermes_listen_in_driver.py`, which now also checks listen-in per profile.
- Follow-up: Bots on the organization Tasks page.

### 2026-11-13 — AF-425 — Task tracking per Bot

- Delivered:
  - `bot-setup.py` copies the `agentbarn-tasks` plugin into each Bot profile; the Bot's own config already enabled it.
  - The plugin reads its identity the way telemetry-push does: the profile's `.env`, else the process environment. It registers only with a full identity, and runs `agentbarn-task` with `AGENT_ID`, `INGEST_URL`, `INGEST_API_KEY` and the `ARTIFACT_*` names from that identity, replaced together so Parent Agent and Bot values never mix.
  - `bot_passthrough_names` always includes `AGENT_ID`, `INGEST_URL` and `INGEST_API_KEY`, so the `agentbarn-task` fallback in a Bot's terminal acts as the Bot.
- Changed: nothing for a pod without Bots, whose plugin keeps reading the process environment (`start.sh` removes `/opt/data/.env`). The API already stored and showed Tasks per Bot.
- Follow-up: listen-in per Bot.

### 2026-11-13 — AF-425 — Observer records only its own profile

- Fixed: the observer's arrival and first-response wrappers patch process-wide classes, so every profile's copy saw every profile's messages. Each copy now works out its profile from where it is installed (`profiles/<id>` for a Bot, none for the Parent Agent) and records only messages that belong to that profile. Like Hermes' own `_session_key_profile`, it takes the profile stamped on the message (`source.profile`, set by shared ingress such as webhooks and the API relay), else the adapter's owner (`_owner_profile`, which `_configure_profile_adapter` sets on every Bot adapter before it handles anything). A Parent Agent's adapters have neither, so in a pod without Bots everything is recorded exactly as before. Hooks such as `pre_gateway_dispatch` already run per profile, because Hermes keeps one plugin manager per profile home.
- Changed: the two Bot identity tests stub the ingress install that staging added to `register`. The Bot image driver runs Hermes' real `_configure_profile_adapter` and checks it names the Bot's profile on its adapter, and none on the default profile's.
- Follow-up: Task tracking per Bot.

### 2026-11-13 — AF-425 — Staging merge (Agent Tasks, listen-in)

- Merged: `origin/staging` through #347, bringing Agent Tasks (AF-411/412/413), Hermes listen-in, the observer's arrival and first-response recording, and the GitLab integration.
- Changed: the two test files that conflicted keep both sides. Migration `3faf5ff99e14` joins staging's head `a9d2e7c4b1f8` with this branch's `d79ce00137d2`. `hermes-base/VERSION` goes to `0.2.12`, because both sides had moved it to `0.2.11`.
- Known gaps, from staging's code assuming one Agent per Hermes process:
  - the observer's new arrival and first-response wrappers patch process-wide classes, so every profile records every profile's messages;
  - the `agentbarn-tasks` plugin isn't installed in Bot profiles, and would act as the Parent Agent if it were;
  - a Bot's terminal runs `agentbarn-task` with the Parent Agent's ingest identity;
  - the listen-in plugin and its startup check never reach a Bot's profile, though a Bot's config enables its rooms;
  - the organization Tasks page shows Bot Tasks without a name or a filter entry.
- Follow-up: fix those four areas, in that order, before the end-to-end run.

### 2026-11-12 — AF-445 — Bots on OpenClaw in the UI

- Delivered: the Bot switcher, the pod-wide "Agent" menu group and the Home Bot count now show for OpenClaw Agents too. The New bot dialog leaves out command approval for an OpenClaw parent and sends none.
- Changed: maintainer decision on 2026-11-12 that every OpenClaw Agent, with or without Bots, groups Logs, File sync, Resource usage, Restore points and Size under "Agent", as Hermes Agents already do. Two navigation tests were updated to that layout.
- Follow-up: the end-to-end run.

### 2026-11-12 — AF-445 — OpenClaw Bot Restore Point exclusions

- Delivered: `restore_point_job.py` leaves out, for each top-level `workspace-<id>/`, the Markdown `bot-setup.py` rewrites and `skills/`, and for each `bots/<id>/`, `.config` (aai-cli config, direct-mode gog keyring), `.local` and `aai-cli` (encrypted store and key). A Bot's `agents/<id>` sessions, `USER.md`, own work and trigger receipts are kept. Tests tie each rule to the code that writes the path.
- Changed: none outside the exclusion sets. Capture tests need `os.O_NOFOLLOW`, so they run on Linux only; all 104 passed there.
- Follow-up: the UI.

### 2026-11-12 — AF-445 — OpenClaw account guard

- Delivered: `agentbarn-bot-env` gains a `before_tool_call` guard on `message` and `automations` (alias `cron`), at priority -1000. When a message, or a scheduled job's `delivery`, `delivery.failureDestination` or `failureAlert`, names a platform, it is pinned to the calling agent's own account (`default` for the Parent Agent, the Bot's id for a Bot). It is blocked, with a reason the model sees, when the agent has no account on that platform or names another agent's account. Routes without a platform, or `last`, and scheduler reads are left alone. The builder passes each agent's platforms in the plugin's config.
- Changed: observed in the pinned image, the scheduler tool is named `automations` and already refuses a job owned by another agent, and `conversations_send` is limited to the calling agent's own conversations, so neither needs more.
- Follow-up: Restore Point exclusions.

### 2026-11-12 — AF-445 — OpenClaw trigger server per Bot

- Delivered: on OpenClaw, `agent-trigger-server.py` reads its agent from `RUNTIME_MODEL` and creates webhook jobs with `--agent <id> --account <id>`, or `--agent main --account default` for a Parent Agent with Bots. A pod without Bots (`openclaw/default`) creates jobs as before. Each Bot's receipts already live in its own file (`bot-run.py`).
- Changed: nothing else; workflow steps already run as the agent through `RUNTIME_MODEL` and the session prefix.
- Follow-up: the account guard.

### 2026-11-12 — AF-445 — OpenClaw per-Bot identity

- Delivered:
  - `telemetry-push` and `agentbarn-observer` resolve each event's agent from `ctx.agentId`, else `agent:<id>:` in the session key, else a non-default `accountId`, and post it to `/agents/<id>/…` with that agent's `INGEST_API_KEY` from `/run/agentbarn/bots/<id>`. The parent keeps its own environment identity; an agent with no matching Secret is dropped. `agent:<id>:main` counts as a DM for every agent, not only `main`.
  - `healthz-server.js` reports each account in `openclaw health --json` (`channels.<platform>.accounts`) under its agent, `default` being the parent, so a platform only a Bot uses is no longer reported as the parent's. `/healthz` lists `served_bots` from `/tmp/agentbarn-active-bots.json`. When the pod has Bots, the spent-limit marker is keyed by a hash of the caller's key, and the adapter reads the one for its own `LITELLM_API_KEY`.
- Changed: `HEALTHZ_HEALTH_COMMAND` overrides the health command for tests only.
- Follow-up: the trigger server per Bot.

### 2026-11-12 — AF-445 — Start and stop OpenClaw Bots

- Delivered: starting an OpenClaw Parent Agent assembles each live Bot (its own Secret and ConfigMap, a Bot that fails is in error and left out), builds the multi-agent gateway config from the Bots' own overlays, sets `RUNTIME_MODEL=openclaw/main`, `RUNTIME_SESSION_PREFIX=agent:main:` and the union of platforms on the parent's Secret, loads `agentbarn-bot-env` with the parent's Secret names, mounts each Bot's Secret and ConfigMap, opens `trg-<slot>` ports and ships `bots.json` with live and deleted Bots. Stopping and deleting already covered every runtime.
- Changed: the line-break refusal now applies to Hermes pods only, since OpenClaw Bots never write an env file. A parent without Bots, or whose last Bot was deleted, gets its single-agent overlay and `openclaw/default`. Pod memory stays the Parent Agent's Agent Size; the feature doc says a parent with several Bots may need a larger one, to be measured in the end-to-end run.
- Follow-up: per-Bot identity.

### 2026-11-12 — AF-445 — OpenClaw command environment plugin

- Delivered: plugin `scripts/openclaw/plugins/agentbarn-bot-env`, on `before_tool_call` for `exec` at priority -1000.
  - A Bot's commands get every value in `/run/agentbarn/bots/<id>`, `AAI_CONFIG` under `bots/<id>` and `ARTIFACT_UPLOAD_ROOTS` set to `workspace-<id>`. Every name in the Parent Agent's Secret that the Bot does not define is blanked, except `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL`, `LITELLM_BASE_URL`, `LITELLM_PROXY_TARGET` and `LLM_PROXY_PORT`.
  - The Parent Agent's commands get its own values for its Secret's names. The model's `env` is kept but never wins over either.
  - An agent with no matching Secret, or no agent id, is refused; the pinned hook runner treats `before_tool_call` as fail-closed and refuses the command. A Bot's code-mode command is refused.
  - `multi_agent_gateway_config(..., parent_env_names=...)` loads the plugin with the parent's Secret names; the ConfigMap ships it with `bots.json` and `start.sh` installs it.
- Changed: observed in the pinned runner, `before_tool_call` gives each handler its own copy of the event and keeps the last handler's `params`, so this plugin wins over any earlier one and also replaces that plugin's own parameter changes. None of today's plugins rewrite `exec`.
- Follow-up: start and stop wiring, which passes the parent's Secret names.

### 2026-11-11 — AF-445 — OpenClaw in-pod boot

- Delivered:
  - `init-openclaw.js` replaces `agents.entries` and deletes `agents.ownership`, `agents.defaults.systemAgent`, `agents.entries`, `litellm-bot-<n>` providers and `bot<n>` secret providers the overlay leaves out; other secret providers stay.
  - `scripts/openclaw/bot-setup.py` writes each Bot's workspace (`workspace-<id>`, instructions pointed at it, skills, its own `USER.md` kept), agent and home directories, runs its aai-cli and gog setup from `/app/bots/<id>`, and writes `/tmp/agentbarn-keys/<id>.json` (0600) with only its LiteLLM key and platform tokens. A Bot without a matching Secret, a LiteLLM key or its ConfigMap, or whose setup fails, is removed from `openclaw.json` and left out of `/tmp/agentbarn-active-bots.json`. Deleted Bots' files go at start; `--clean-jobs` removes their scheduled jobs in the background once the gateway lists them.
  - `scripts/openclaw/bot-run.py` runs a served Bot's adapter and trigger server with its own Secret, the parent's gateway token and URL, `openclaw/<id>`, port `8100 + slot` and its own receipts file.
  - `start.sh` sets Bots up after the parent's integrations and launches their helpers and the job cleanup just before the gateway.
  - The adapter and trigger server prefix OpenClaw session keys with `RUNTIME_SESSION_PREFIX`; a parent with Bots gets `agent:main:`, a Bot `agent:<id>:`.
- Changed: the parent's ConfigMap ships `bot-setup.py` and `bot-run.py` with `bots.json`. Observed in the spike pod: a job whose agent was removed failed with "cron job agent is unavailable" instead of running as the parent.
- Follow-up: the exec plugin.

### 2026-11-11 — AF-445 — OpenClaw multi-agent builders

- Delivered, in `builders/openclaw.py` and not yet called by the service:
  - `multi_agent_gateway_config` turns a parent's gateway config into a multi-agent one: explicit ownership with `main` as the system agent, one entry per Bot with its own workspace, agent directory and `litellm-bot-<slot>` provider, whose key is a file reference to `/tmp/agentbarn-keys/<bot-id>.json`.
  - On a platform a Bot uses, the parent moves to account `default` and each Bot gets account `<bot-id>` with its own token references; the channel root keeps no policy. A platform only the parent uses stays as it was. Every account has a binding to its agent.
  - Channel plugins and the observer cover every Bot's platform. Active memory covers every agent. Hindsight ignores `agent:<bot-id>:**` sessions, and a Bot's own memory setting never turns automatic memory on. `tools.agentToAgent` is off.
  - `multi_agent_runtime_env` gives a parent with Bots `RUNTIME_MODEL=openclaw/main` and the union of platforms in `AGENTBARN_NATIVE_CHANNELS`.
  - `build_deployment(bot_ids=...)` mounts each Bot's Secret and ConfigMap, and `build_config_map(bots_manifest=...)` ships `bots.json`.
  - Without Bots every output is unchanged.
- Changed: the per-Bot Secret and ConfigMap mounts moved to `builders/common.py`; the Hermes Deployment is unchanged. New image contract `runtime_tests/test_openclaw_bots.py`.
- Follow-up: in-pod boot.

### 2026-11-11 — AF-445 — Bots on OpenClaw Parent Agents in the API

- Delivered:
  - `POST /agents/{id}/bots` on an OpenClaw Parent Agent creates a stopped OpenClaw Bot with approval `auto`, no turn limit and File Sync off.
  - The Hermes-only Bot rules (manual-approval mixing, read-only turn limit) skip OpenClaw Bots; OpenClaw's own 400s for approval, verbose mode and turn limit apply instead.
  - An OpenClaw Bot's own or shared Firecrawl credential is refused with 400, on create and on update.
  - An OpenClaw Bot's integration files live under `/home/node/.openclaw/bots/<id>`, with its aai-cli store in `aai-cli` below it and the shared gog shim in `/home/node`.
- Changed: the 400 "Only Hermes Agents can hold Bots" is gone. No schema or contract change. Agent Memory needs no API rule; the memory tool per Bot comes with the runtime slices.
- Follow-up: the multi-agent configuration builders.

### 2026-11-11 — AF-445 — Bots share their parent's runtime

- Delivered: migration `865ce7d7db04`. `trg_agent_bot_parent` now requires a Bot to use its Parent Agent's runtime, Hermes or OpenClaw, and refuses changing a Parent Agent's runtime while it has Bots. Downgrade restores the Hermes-only rule without rechecking existing rows.
- Changed: schema rule only; no model or API change.
- Follow-up: Bot creation for OpenClaw Parent Agents.

### 2026-11-11 — AF-445 — OpenClaw Bots documentation

- Delivered: the OpenClaw Bots contract in the feature doc, the runtime-neutral Bot terms, the ADR, and the OpenClaw spike evidence.
- Changed: docs only. `CONTEXT.md` drops the superseded rule that a Bot cannot share a Platform with its Parent Agent.
- Follow-up: the migration letting a Parent Agent and its Bots share either runtime.

### 2026-11-09 — AF-425 — Staging merge

- Fixed: staging's save-and-restart on `PATCH /agents/{id}` is refused on a Bot, because it would create a separate pod. Saving integrations on a running Bot restarts its Parent Agent from the UI instead.

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
