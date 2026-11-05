# Agent Personas

**Not yet available.** Nothing below is implemented. This is the contract the [AF-425 delivery slices](agent-personas/CHANGELOG.md) build towards, and each slice moves what it delivers into current behaviour here. See the log for what has landed.

## Read when

Read before changing Personas, Persona Versions, how a Persona reaches its Hermes profile, Web Chat Persona routing, or the boot step that lays out profiles.

## Role in the system

A Persona lets one Agent present several identities, such as Sales or Lawyer, without another pod or another bot install. Each Persona is a Hermes profile served by the Agent's one `hermes gateway run` process. v1 covers the Hermes Runtime and Web Chat only.

The decision and its trade-offs are in the [ADR](../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md).

## What is per Persona and what is shared

| Per Persona | Shared across the Agent |
|---|---|
| Name and emoji | Pod, Agent Size, volume, Restore Points |
| SOUL and IDENTITY, versioned | The pinned Template's AGENTS, TOOLS, BOOT, HEARTBEAT and required Skills |
| Sessions and built-in memory | Runtime and Configured Model |
| Scheduled jobs | Model key and Model Spend Limit |
| Web Chat threads | Agent Secrets, Integrations, credential gateway tokens |
| | Communication Connections, Agent Memory, RBAC and Agent Access |

The working directory `/workspace` is shared too, because Hermes sets it once per process.

## Invariants

- **Not a security boundary.** Personas share the filesystem, process and keys. Anything that needs hard isolation, or a different account for the same provider, needs a separate Agent. Product copy must not imply otherwise.
- **The Default Persona is the Agent.** It has no row: a null `persona_id` means the Default everywhere. Its identity stays with the Template or Override, and it can't be edited or deleted as a Persona.
- **At most 5 active Personas per Agent,** not counting the Default.
- **SOUL and IDENTITY are capped at 32 KiB each,** in UTF-8 bytes.
- **Keys are server-derived and immutable.** A key is at most 40 characters, so the longest runtime session id stays within Hermes's 256-character limit. It is never reused, even after deletion, and avoids names Hermes reserves or File Sync can't sync.
- **Persona Versions are immutable.** Saving changed SOUL or IDENTITY appends one.
- **Changes need a stopped Agent.** Create, edit and delete are refused while the Agent runs, as other runtime configuration is. The UI wraps them in Apply & Restart.
- **Authorization follows the Agent.** Reading needs `agent.read`, and changes need `agent.update`. There is no per-Persona access and no new Permission. See the [RBAC brief](rbac/IMPLEMENTATION-BRIEF.md).
- **Hermes only in v1.** Changing Personas on an OpenClaw Agent is refused with 400.
- **A deployment flag gates the feature** until the UI is complete.
- **Multiplex only with Personas.** An Agent with no active Persona keeps its single-profile boot, with no `.env` file and no in-memory volume.
- **A Persona message never runs as the Default.** With multiplex off, Hermes silently answers an unknown `/p/<key>` as the Default, and it serves any profile folder it finds, so the adapter only addresses keys on the active list and fails any other.
- **Bot tokens never go in a Persona's `.env`.** Hermes refuses the duplicate adapter, but the Persona never needs them.

## Secrets

Under multiplex, Hermes reads secrets for agent turns only from each profile's `.env`, not from the process environment. At boot, values already in the pod are written to a memory-backed volume at `/run/agentbarn/env`, and each profile's `.env` is a symlink to them. No new secret enters the pod, and nothing goes on the Agent's volume or in Restore Points.

- **A Persona's `.env` holds:** `API_SERVER_KEY`, `OPENAI_API_KEY`, `OPENROUTER_BASE_URL`, `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL` and `HINDSIGHT_API_KEY`. Losing the Firecrawl key falls back silently to keyless search, and losing the Hindsight key silently sends unauthenticated calls.
- **The Default's `.env` also holds every connected platform's settings.** Without them, a Telegram user allowed only in DMs is admitted to groups that aren't allowed.
- **A terminal can read these files.** That is not new access: the terminal user can already read the gateway's environment through `/proc/1/environ`.

## Approvals

"Always" is Agent-wide and survives restarts. Hermes keeps one process-wide list, loaded from whichever profile runs first after boot, and saves it only to the active profile. So before the gateway starts, the boot step copies the newest-saved list into every profile. A stale save can drop a grant, which shows as a repeat prompt.

## Files

- **Per-Persona paths:** `/opt/data/profiles/<key>/` holds SOUL, IDENTITY, config, sessions and memories. Daily notes are in `/workspace/personas/<key>/memory/`.
- **Terminal paths:** `$HERMES_HOME` in a Persona's terminal stays `/opt/data`, so Persona instructions use absolute paths. A profile must never have a `home/` folder, or Hermes moves `HOME` and tools lose their stores under `/opt/data`.
- **File Sync:** a Persona's `USER.md`, `MEMORY.md` and daily notes are mirrored, and any Organization Member can edit them at the provider, the [gap already accepted](../adr/2026-10-21-agent-file-sync-through-sync-provider.md) for an Agent's files. SOUL, IDENTITY, config, sessions and `.env` are never mirrored. IDENTITY stays out of `/workspace` for this reason.
- **Prototype config:** a Persona's `config.yaml` is a copy of the Agent's managed config with only platform sections and plugins changed, plus `/opt/data/skills` so it sees the bundled skills.

## Accepted limitations

- Tool Calls, Activity, logs and Playbook transcripts aren't labelled by Persona.
- All Personas share Hermes's limit of 10 concurrent runs. Over it, a run gets 429 and the delivery counts as failed.
- Stop suppresses the reply but doesn't abort a Hermes run, as today.
- Native platforms such as Slack serve the Default only.
- A Persona's scheduled jobs run unattended and bill to the Agent. Their results stay in the profile and don't reach Web Chat, which has no scheduled pushes.
- Deleting a Persona makes its Web Chat history unreachable in the product, though messages stay in the database. Its folders go at the next start, and mirrored notes and memory go to the provider's recycle bin.
- Restoring a Restore Point doesn't roll Persona rows back. A deleted Persona stays deleted even if the archive has its files. A Persona created after the capture restarts with empty Hermes sessions and memory, while its Web Chat history stays.

## Change impact

- **Upgrading Hermes:** this feature relies on `v2026.8.19`, where multiplex is opt-in. The current [Hermes documentation](https://hermes-agent.nousresearch.com/docs/user-guide/multi-profile-gateways) says multiplex is on by default and turning it off is retired. "Multiplex only with Personas" therefore can't survive an upgrade unchanged: single-Persona Agents would need the `.env` setup too. Any Hermes bump must revisit it and rerun the multiplex checks.
- **New secrets a turn reads:** must be added to the `.env` lists above.
- **New Connection settings:** must reach the Default's `.env`.

## Related decisions

- [Personas are Hermes profiles in one pod](../adr/2026-11-04-personas-are-hermes-profiles-in-one-pod.md)
- [Agent file sync through the Sync Provider](../adr/2026-10-21-agent-file-sync-through-sync-provider.md)
