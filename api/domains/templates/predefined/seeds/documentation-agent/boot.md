# BOOT.md

On startup, orient yourself to the event type and the latest relevant context.

## 1. Setup Check

Read USER.md. If the Required fields (Confluence space + parent, Slack digest
channel) are empty — or no source-control host is usable (no GitHub/Bitbucket
repos mapped and USER.md's **Repos to document** is also empty):
- **Slack DM or mention**: run the Setup Flow (AGENTS.md) instead of normal
  handling. Stop here.
- **Cron job**: skip all cron work; reply `HEARTBEAT_OK`.

## 2. Cron Maintenance

Ensure the two recurring cron jobs exist. Create any that are missing (creation is
idempotent):
- **doc-scan** — daily (`0 6 * * *`)
- **weekly-digest** — weekly, default Monday 09:00 (`0 9 * * MON`)

## 3. Event Handling

- **Named cron job** (doc-scan, weekly-digest): run the corresponding loop in
  AGENTS.md. If no action is needed, reply `HEARTBEAT_OK`.
- **Slack DM or mention**: answer questions about what's been documented, or
  re-run a scan on request; read the narrowest relevant sources.
- **Direct operator request**: do the requested task; call out missing data.

Only create or update your own auto-generated Confluence pages and the changelog;
never overwrite human content. Read the relevant skill file before calling
`aai-cli`.

If the task sends a message, use the message tool and then reply with the exact
silent token `NO_REPLY` / `no_reply`.
