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
  Bots can be created, but nothing runs them yet, and lifecycle routes still accept a Bot.
- In transition: until the next slice, start, stop and other pod operations are not refused on a Bot.
- Next: refusals and redirects for pod operations on a Bot, and cascaded delete.
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
