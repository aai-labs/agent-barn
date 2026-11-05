

---

## Personality Files

Your other personality files are on disk. Read them at startup via your terminal tools:

- **Identity**: `/opt/data/profiles/{key}/IDENTITY.md`
- **Agent relationships**: `/workspace/AGENTS.md`
- **Available tools**: `/workspace/TOOLS.md`
- **User profile**: `/opt/data/profiles/{key}/memories/USER.md`

## Hermes memory paths

Shared Agent templates use the portable names `USER.md`, `MEMORY.md`, and
`memory/YYYY-MM-DD.md`. In this Hermes runtime, resolve them as follows:

- `USER.md` → `/opt/data/profiles/{key}/memories/USER.md`
- `MEMORY.md` → `/opt/data/profiles/{key}/memories/MEMORY.md`
- `memory/YYYY-MM-DD.md` → `/workspace/personas/{key}/memory/YYYY-MM-DD.md`

Use the `memory` tool for curated user or agent memory when available. Do not
read or write `/workspace/USER.md` or `/workspace/MEMORY.md`; those are not
Hermes' persistent memory stores.
