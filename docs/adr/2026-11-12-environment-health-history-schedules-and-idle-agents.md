# Add history, schedules, builds and idle Agents to environment health, still with no cluster text

Status: Proposed
Date: 2026-11-12
Origin: AF-448

On staging (AF-436) the volume-claim quota sat at 60 of 60 and scheduled backups failed from Nov 6, CPU limits spiked to 97–99% of the quota whenever cron jobs started together, two services crash-looped (one OOM-killed 15 times), deploys failed for six days, and idle Agents held quota. The environment health page showed none of it, because every figure was as of now and it never looked at schedules, builds or use. This adds those to the page as Platform Oversight Data under the [environment health ADR](2026-10-20-environment-health-as-platform-oversight-data.md), which says a new field is a classification decision.

## Considered alternatives

- **Store history in the database.** The in-namespace Prometheus already keeps 15 days of kube-state-metrics pod series, which is enough for a 24-hour peak and a 7-day restart history. A table of our own would need a writer and retention for what Prometheus already holds.
- **Add the kube-state-metrics `cronjobs` and `jobs` collectors.** The tenant account can list CronJobs and Jobs directly (checked with `kubectl auth can-i --list` in both namespaces), and a direct read gives `lastSuccessfulTime` without a new scrape. The collectors stay at `pods`.
- **Count any model call as use.** On Oct 27 the platform woke every Agent at once. Cost records cannot tell a person's request from a heartbeat or a platform restart, so only a message a person sent counts as use; the last model call is shown beside it for context.
- **Parse each CronJob's schedule to judge when it is late.** That needs a cron parser, which is a new dependency. Every platform CronJob runs at least hourly, so "no success for a day" is a stall whatever the schedule.

## Consequences

- The read model adds:
  - for capacity lines, a 24-hour peak and its ratio;
  - for pods, restarts within a 7-day window and whether a container was OOM-killed in it;
  - for each platform Deployment, its `build-sha` annotation (kept only as 7–40 hex characters), its rollout state from the `Progressing` condition's reason, and when its last rollout finished;
  - the newest build and the services on another one;
  - for each platform CronJob, its name, a schedule kept only when it matches the cron grammar, whether it is suspended or running, and the times of its last schedule, last success and last failure;
  - for scheduled backups, the interval, and per Agent the count and time of failures in 24 hours and the time of its last successful one;
  - for idle Agents, the time of the last message a person sent and of the last model call, and counts and sizes of what each one holds.
- It carries no Job or condition messages, no CronJob command or arguments, no `failure_reason` of a restore point, no message content, and no annotation other than `build-sha`.
- The new cluster reads (Services, CronJobs, Jobs) are optional sources like the rest. A refusal shows as "not permitted" and the rest of the page renders. The backups and idle-Agent parts read only the database, so they work with no cluster at all.
- The conversation, activity and restore-point services each gain one platform-wide read with no Organization scope, returning times or counts by Agent id. They are for `require_platform_admin` routes only, as `find_live_for_platform_usage` is.
- A peak sampled every 30 seconds can still miss a burst shorter than one scrape.
- Idle Agents are listed for a person to act on. The page stops and deletes nothing, and an idle Agent does not change the page's level.
