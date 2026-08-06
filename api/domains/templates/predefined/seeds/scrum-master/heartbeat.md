# HEARTBEAT.md

Run these checks when heartbeat context is available. If there is no useful action, reply with `HEARTBEAT_OK`.

Keep this file small — it is read on every recurring wake.

## Guard

If USER.md Required fields (team lead, Jira keys, Confluence keys) are empty, skip all cron work and reply `HEARTBEAT_OK`. Setup runs on the next Slack message, not during heartbeats.

## Named Cron Jobs

When a cron job fires, the heartbeat context includes its name. Follow the matching loop in AGENTS.md:

- **blocker-scan** → cron:blocker-scan
- **sprint-check** → cron:sprint-check
- **context-gap** → cron:context-gap

## Fallback (no cron name in context)

If the heartbeat context includes no cron job name, run all three loops in sequence:

1. cron:blocker-scan (AGENTS.md)
2. cron:sprint-check (AGENTS.md)
3. cron:context-gap (AGENTS.md)
