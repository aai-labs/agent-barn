# HEARTBEAT.md

Run these checks when heartbeat context is available. If there is no useful action, reply with `HEARTBEAT_OK`.

Keep this file small — it is read on every recurring wake.

## Guard

If `Setup complete: yes` is absent from USER.md, skip all cron work and reply `HEARTBEAT_OK`. Setup runs on the next Slack message, not during heartbeats.

## Named Cron Job

When the cron job fires, the heartbeat context includes its name. Follow the matching loop in AGENTS.md:

- **review-health-scan** → cron:review-health-scan

## Timing constraint

Do not take action between 22:00 and 08:00 in the operator's timezone. During nighttime wakes reply `HEARTBEAT_OK` — the morning tick will handle the PR scan.

## Cron is the scan trigger

The review-health-scan cron actively fetches open PRs and prompts the team lead. This is intentional — the agent surfaces what needs review proactively, but waits for the team lead to confirm before starting each review.

## No unnamed work

If there is no cron job name in the heartbeat context, reply `HEARTBEAT_OK`.
Only the explicit `review-health-scan` cron may fetch pull requests or prompt
the team lead.
