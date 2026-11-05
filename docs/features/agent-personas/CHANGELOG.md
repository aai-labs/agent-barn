# Agent Personas — change log

Status: Active
Epic: AF-425
Related context: [`../agent-personas.md`](../agent-personas.md), [`../../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md`](../../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: terminology, the feature contract and the ADR. No product behaviour has changed.
- In transition: nothing.
- Next: `agent_persona` and `agent_persona_version` tables and models, and the `docs/INDEX.md` entry for the new domain.
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

### 2026-11-05 — AF-425 — docs groundwork

- Delivered: Persona terms in `CONTEXT.md`, the feature contract, the ADR, this log and the `docs/INDEX.md` routes.
- Changed: documentation only.
- Follow-up: persistence slice.
