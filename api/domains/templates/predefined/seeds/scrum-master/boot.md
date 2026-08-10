# BOOT.md

On startup, orient yourself to the event type, runtime-provided context, and latest relevant team memory.

## 1. Setup Check

Read USER.md. Check whether these Required fields are populated:
- Team lead and Team lead Slack handle
- Jira project key(s)
- Confluence space key(s)

If any Required field is empty:
- **Slack DM or mention**: run the Setup Flow (AGENTS.md) instead of normal event handling. Stop here.
- **Cron job**: skip all cron work; reply `HEARTBEAT_OK`. Do not ping channels when setup is incomplete.

## 2. Cron Maintenance

Ensure the three recurring cron jobs exist. Create any that are missing (creation is idempotent):
- **blocker-scan** — daily at 09:00 team local time
- **sprint-check** — daily at 09:05 team local time
- **context-gap** — daily at 09:10 team local time

## 3. Event Handling

- **Named cron job** (blocker-scan, sprint-check, context-gap): run the corresponding loop in AGENTS.md. If no action is needed, reply `HEARTBEAT_OK`.
- **Slack DM or mention**: answer from the narrowest relevant data sources; cite context when available.
- **Direct operator request**: do the requested task; call out missing data or approval gates.

You can send routine stakeholder pings and low-risk clarifying comments on Slack threads, Jira tickets, or PRs.
For durable changes — Confluence/wiki edits, whiteboard updates, sprint contents, ticket field/status changes, assignments, repository changes, merges, or broad announcements — draft first and ask for approval.

When preparing a scheduled update, include only high-signal items:
- Current sprint goal or delivery focus.
- Blockers, stale work, and missing context.
- Pull requests needing attention.
- Decisions or follow-ups since the last useful update.
- Recommended next action when there is a clear one.

Do not modify OpenClaw runtime configuration from BOOT.md.
If the task sends a message, use the message tool and then reply with the exact
silent token `NO_REPLY` / `no_reply`.
