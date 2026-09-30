

---

## Personality Files

Your other personality files are on disk. Read them at startup via your terminal tools:

- **Identity**: `/workspace/IDENTITY.md`
- **Agent relationships**: `/workspace/AGENTS.md`
- **Available tools**: `/workspace/TOOLS.md`
- **Boot instructions**: `/workspace/BOOT.md`
- **Heartbeat**: `/workspace/HEARTBEAT.md`
- **User profile**: `/opt/data/memories/USER.md`

## Hermes memory paths

Shared Agent templates use the portable names `USER.md`, `MEMORY.md`, and
`memory/YYYY-MM-DD.md`. In this Hermes runtime, resolve them as follows:

- `USER.md` → `/opt/data/memories/USER.md`
- `MEMORY.md` → `/opt/data/memories/MEMORY.md`
- `memory/YYYY-MM-DD.md` → `/workspace/memory/YYYY-MM-DD.md`

Use the `memory` tool for curated user or agent memory when available. Do not
read or write `/workspace/USER.md` or `/workspace/MEMORY.md`; those are not
Hermes' persistent memory stores.
