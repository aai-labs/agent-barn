# Agent Personas — change log

Status: Active
Epic: AF-425
Related context: [`../agent-personas.md`](../agent-personas.md), [`../../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md`](../../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: terminology, the feature contract, the ADR, the tables and `persona_id` columns, and Persona routes to read, create, edit and delete, with creation behind the `personas_enabled` flag, which is off by default. An Agent with Personas now starts them as Hermes profiles under multiplex, but nothing routes messages to them yet, and this hasn't run against a real pod.
- In transition: nothing.
- Next: Restore Point exclusions.
- Note: the re-check that refuses a send for a Persona deleted in the meantime arrives with the Communications slice, which is also what first writes `persona_id` on messages.
- Blockers: none.

## Runtime evidence

From a spike against Hermes `v2026.8.19` in local k3d. Later slices may rely on these.

**Observed working:**
- One gateway process served the Default and two Personas, each with its own SOUL, `state.db` and memory files, including under five concurrent runs.
- `/p/<key>/v1/runs`, its events and approvals worked, with resume. An unknown key returned 404 and a wrong key 401.
- A session id of 256 characters was accepted; 257 returned 400.
- Profiles and `.env` links came back after a pod replacement, a container restart and a kill mid-run.
- Removing the last Persona and multiplex left the Default working, with its old sessions.
- With bot tokens out of Persona `.env` files there was no duplicate adapter. With them in, Hermes reported `duplicate_credential` and stayed up.
- Tool calls reached Ingest once.
- Nothing from `profiles/` reached File Sync's report, and a memory file replaced by rename was seen on the Persona's next run.

**Observed behaviour that shapes the design:**
- "Always" loads from whichever profile runs first after boot. Copying the newest-saved list to every profile before boot made grants durable in any order, and revokes held.
- With Telegram's settings only in the process environment, a user allowed only in DMs was admitted to a non-allowed group. With them in `default.env`, all seven cases matched.
- Without its key, Firecrawl silently fell back to keyless search, and Hindsight calls went out unauthenticated.
- `$HERMES_HOME` in a Persona terminal stayed `/opt/data`.
- A `${X}` value is expanded by `load_dotenv` but not by Hermes's scoped reader.
- With multiplex off, `/p/<anything>` ran as the Default. A profile folder not listed as deleted was served.

**Measured:**
- About 10 MiB per Persona: 162 MiB idle with none, 195 MiB with five. Peak at 10 concurrent runs was 454 MiB.
- Run cap: 10 across Personas, then 429.
- Worst insert wait while adding the message foreign key, on a small local Postgres and so only a guide:

| Rows | Plain FK | Two-step |
|---|---|---|
| 1M | 4.0 s | 0.011 s |
| 10M | 15.4 s | 1.0 s |

- A failed or cancelled second step resumed on retry, and a long reader made the first step fail on `lock_timeout` instead of hanging.

**Not proven:** real Slack, Telegram and Discord connections (offline adapter and gate checks only; the Slack check skipped approval buttons); real Hindsight (stub only); the Firecrawl browser (not configured locally); web search on the Default; skill-declared passthrough variables; `agentbarn-observer` under multiplex; cron `deliver: local` and `origin` completing; Restore Point capture of a multi-Persona volume.

## Changes

### 2026-11-05 — AF-425 — Persona runtime wiring

- Delivered: the start flow loads Personas and renders them into the ConfigMap with `personas.json`, each current SOUL and IDENTITY, and a per-Persona footer pointing at its own paths. An active Persona adds `GATEWAY_MULTIPLEX_PROFILES=1` and the in-memory volume. `default_env_names` carries every connected platform's settings. `start.sh` runs both `persona-setup.py` steps only when `personas.json` exists. Starting is refused with 409, before anything is torn down, when a secret value has a line break or the ConfigMap would exceed 1,000,000 bytes.
- Changed: `AgentService` gains a `PersonaRepository`. The runtime digest moves, so running Agents will report an available update.
- Follow-up: Restore Point exclusions, then image-level tests.

### 2026-11-05 — AF-425 — Persona boot script

- Delivered: `scripts/hermes/persona-setup.py`, tested on its own. It lays out each Persona's profile, writes the `.env` files to the in-memory folder and links them, removes deleted Personas' folders, and with `--sync-allowlists` copies the newest-saved approvals to every profile. A failure on one Persona is logged and the others continue; a failure writing the Default's `.env` stops the boot. Values with a newline or `${` are left out by name.
- Changed: nothing runs the script yet. The tests skip on machines that can't create symlinks.
- Follow-up: wire it into the builders and `start.sh`.

### 2026-11-05 — AF-425 — Persona delete

- Delivered: `DELETE .../personas/{key}` under `agent.update`, a soft delete with the same guards as edit. The key stays taken and versions stay stored, and it frees a slot. It cancels that Persona's open inbound deliveries in the same transaction: PENDING becomes CANCELLED, and PROCESSING is flagged and ends CANCELLED when its lease is reclaimed. Other Personas and the Default are untouched.
- Changed: one operation added to the public API inventory.
- Follow-up: the boot step.

### 2026-11-05 — AF-425 — Persona create and edit

- Delivered: `POST .../personas` and `PUT .../personas/{key}` under `agent.update`. Keys are derived from the name by the server and never reused. At most 5 active Personas, and SOUL and IDENTITY capped at 32 KiB each in UTF-8 bytes. Text changes append a Persona Version; a stale `expected_version` gets 409. Refused while the Agent runs, during a managed update or a restore, and with 400 on OpenClaw. Each change emits `agent.updated` without any prompt text.
- Changed: two operations added to the public API inventory.
- Follow-up: delete.

### 2026-11-05 — AF-425 — Persona read API

- Delivered: `GET .../personas`, `GET .../personas/{key}` and `GET .../personas/{key}/versions` under `agent.read`. The list starts with the Default and leaves out SOUL and IDENTITY. `default` returns the pinned Template's rendered text. OpenClaw Agents only have the Default.
- Changed: new `personas_enabled` setting (`PERSONAS_ENABLED`, chart value `personasEnabled`), three operations added to the public API inventory.
- Follow-up: create and edit.

### 2026-11-05 — AF-425 — Persona columns on messages and threads

- Delivered: nullable `persona_id` on `agent_chat_message` and `web_chat_thread`, where null means the Default. A message can only name a Persona of its own Agent. The Default and each Persona can each have a thread of the same name. A Persona with history can't be removed on its own, and deleting its Agent or Organization still works.
- Changed: migrations `c1a84f7e2b60` and `d9e36b05a7c2`. Both foreign keys are `DEFERRABLE INITIALLY DEFERRED`, because a plain `NO ACTION` key failed Organization deletion in testing. The spike timed the two-step migration before this change, without the deferred option and with a different column set.
- Follow-up: the read API.

### 2026-11-05 — AF-425 — Persona tables

- Delivered: `agent_persona` and `agent_persona_version`. A key is unique per Agent, including deleted rows, and capped at 40 characters. Foreign keys tie each row to its Agent's Organization. Deleting an Agent removes its Personas and versions; removing a version's author keeps the version.
- Changed: migration `b7d2e94c1a30`, new domain `api/domains/personas/`, models only.
- Follow-up: message and thread columns.

### 2026-11-05 — AF-425 — docs groundwork

- Delivered: Persona terms in `CONTEXT.md`, the feature contract, the ADR, this log and the `docs/INDEX.md` routes.
- Changed: documentation only.
- Follow-up: persistence slice.
