# HEARTBEAT.md - Periodic Checks for {{ agent_display_name }}

Default posture is **quiet by default**: only act on heartbeats when there's something a human will actually thank you for surfacing. Keep this file small — it is read on every recurring wake.

## Guard

If USER.md does not contain `Setup complete: yes`, reply `HEARTBEAT_OK` and stop. Setup runs on the next Slack message, not during heartbeats.

## When to act on a heartbeat

Reply with something useful only when one of these is true:

- A brief request you acknowledged is sitting **>30 minutes** unposted and you have everything you need to finish it. Finish it and post (Slack thread first, then the ticket comment, per BOOT.md).
- You posted a brief with an open question in *Gaps* (a contradiction, missing AC) that has been **stale >24 hours**, and the ticket is in an active sprint. Post one short nudge in the same thread, not a new top-level message.
- A ticket you briefed this week has materially changed (new AC, edited description) **and** the review is still pending in the originating thread. Post a one-line "the brief for <KEY> is stale — AC changed on <date>; want a refresh?" in that thread.

Otherwise reply `HEARTBEAT_OK` and stop.

## When to stay quiet

- It's late (23:00–08:00 in the originating user's timezone) — defer non-urgent things to the morning.
- Nothing has changed since the last heartbeat.
- You already nudged once on the same thread today.
- The originating channel is in casual conversation and not waiting on you.

## Don't proactively scan the backlog

Heartbeats are not a replacement for being summoned. Do not poll Jira for new tickets and produce unsolicited briefs, and do not audit ticket quality across the board — that's the scrum master agent's beat, not yours. The agent briefs on request, not on its own initiative.

## Token budget

Keep heartbeat work small. If you find yourself fetching a full ticket-and-docs tree inside a heartbeat tick, stop and instead post "the brief for <KEY> may be stale — should I refresh it?" in the originating thread.
