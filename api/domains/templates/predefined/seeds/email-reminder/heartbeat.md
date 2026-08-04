# HEARTBEAT.md

Run the email check when a heartbeat fires.

## Guard

If `USER.md setup_complete` is `false`, skip all work and reply `HEARTBEAT_OK`.

## Named Cron Job

When the heartbeat context names the cron job **email-check**, run cron:email-check in AGENTS.md.

## Fallback

If the heartbeat context includes no cron job name, run cron:email-check anyway (this is the only scheduled loop for this agent).
