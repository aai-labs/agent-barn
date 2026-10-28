# Silent contributors — change log

Status: Active
Epic: MDP-118 "Make Agents silent contributors in group chats"
Related context: [runtime and deployment](../../architecture/runtime-and-deployment.md#mention-gating), [Agents](../agents.md), [communications](../communications/CHANGELOG.md), [business value](../business-value.md)

An Agent listens in chosen shared channels without being mentioned, keeps the conversation as context, and posts only when it has something useful to add. Mentions are still required everywhere else. Ticket 1 delivers this on OpenClaw for Slack, Discord and Telegram; ticket 2 plans Hermes separately. Teams is out of scope until OpenClaw's Teams plugin supports room events.

## Current state

- Delivered: the PR 0 spike on OpenClaw 2026.8.2, recorded below. No product behaviour has changed yet.
- In transition: nothing.
- Next: PR 1, which removes Discord's "Require @mention" switch on both runtimes.
- Blockers: none. Not verified: Hindsight memory on listen-in turns (the spike Agent had Memory off).

## Changes

### 2026-10-28 — MDP-118 PR 0 — spike

- Delivered: evidence from one local OpenClaw Agent connected to Slack, Discord and Telegram, with a hand-edited config overlay. The Agent used `openrouter/z-ai/glm-5.2`.
- Changed: nothing in product code.
- Findings:
  - **Mechanism.** `messages.groupChat.unmentionedInbound: "room_event"`, plus `requireMention: false` on a room, turns unmentioned messages in that room into room events. The Agent's final text stays private, and it posts only by calling the message tool. Mentions keep normal replies. Rooms that require a mention are unaffected. This held on all three platforms.
  - **Config.** `openclaw config validate` and all three channel plugins accept the room-level keys. A listen-in room entry coexists with the `"*"` entry on Discord (channel) and Telegram (group); the wildcard still admits other rooms as mention-only.
  - **Per-room rules are required.** With only OpenClaw's built-in participation rule, the Agent answered small talk twice and stayed silent on a factual error. With a per-room `systemPrompt` listing when to speak (factual errors, missing context, risks, unanswered questions) and when to stay silent (greetings, small talk, thanks, messages aimed at others), it judged 14 of 15 listen-in messages correctly across the three platforms. The miss was one Telegram reply to "how are you?"; three later small-talk messages there stayed silent.
  - **Where posts land.** Slack posts in a thread under the triggering message. A Discord mention auto-creates a thread. Silent turns show no reaction; mentions keep the ack reaction.
  - **Slack "Start only".** An unmentioned reply in a thread the Agent joined is still a normal request, not a room event, so the Agent answers questions in its own thread and declines bare acknowledgements. Mention-only channels behave as before.
  - **Conversations.** Only messages that really reached the platform are recorded as outbound, so silent turns leave no outbound row. The planned telemetry fix (PR 2) is dropped.
  - **Cost.** Every listen-in message runs a full model turn of about 22–25k prompt tokens, even when the Agent stays silent: about $0.0005 with a cache hit and $0.012–0.016 without on this model. Each such message also counts as a Request.
  - **Config persistence.** `init-openclaw.js` deep-merges `messages` into the config persisted on the volume, so the builder must always write `unmentionedInbound` explicitly rather than omit it.
  - **Unrelated bug found.** Changing a native Connection while an OpenClaw Agent is still on its first start leaves a migration lease on the volume. The next start crash-loops until the 300-second lease expires, because the stale-owner check only matches the same hostname.
- Follow-up:
  - PRs 3–5 write the per-room `systemPrompt` for every listen-in room and always write `unmentionedInbound`.
  - The first-start crash loop goes to a separate ticket.
