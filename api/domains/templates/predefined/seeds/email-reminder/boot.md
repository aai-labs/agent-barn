# BOOT.md

On startup, orient yourself and route to the correct behavior.

## 1. Setup Check

Read USER.md. Check whether `setup_complete` is `true`.

If `setup_complete` is `false`:
- **Slack DM or mention:** run the Setup Flow (AGENTS.md). Stop here.
- **Cron job:** skip all work; reply `HEARTBEAT_OK`. Setup must be completed via a Slack message.

## 2. Cron Maintenance

If setup is complete, ensure the **email-check** cron job exists with the schedule matching `check_frequency` in USER.md. Create it if missing (creation is idempotent).

## 3. Event Handling

- **Named cron job (email-check):** run cron:email-check in AGENTS.md.
- **Slack DM or mention:** answer from USER.md context; do not trigger a full email check unless explicitly asked.
- **Direct operator request:** do the requested task; call out missing data or approval gates.

If the task sends a message, use the message tool and then reply with the exact
silent token `NO_REPLY` / `no_reply`.
