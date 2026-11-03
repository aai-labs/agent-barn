# Silent contributors — change log

Status: Active
Epic: MDP-118 "Make Agents silent contributors in group chats"
Related context: [runtime and deployment](../../architecture/runtime-and-deployment.md#mention-gating), [Agents](../agents.md), [communications](../communications/CHANGELOG.md), [business value](../business-value.md)

An Agent listens in chosen shared channels without being mentioned, keeps the conversation as context, and posts only when it has something useful to add. Mentions are still required everywhere else. Ticket 1 delivers this on OpenClaw for Slack, Discord and Telegram; ticket 2 plans Hermes separately. Teams is out of scope until OpenClaw's Teams plugin supports room events.

## Current state

- Delivered: the PR 0 spike on OpenClaw 2026.8.2, recorded below. PR 1: Discord always requires a mention on both runtimes; its "Require @mention" setting is retired (schema version 3, migration `16ac819db080`). PR 3: OpenClaw turns unmentioned chatter into room events, and Slack Connections have Listen-in channels. PR 4: Discord Connections have Listen-in channels. PR 5: Telegram Connections have Listen-in groups. PR 5b: OpenClaw transcripts record replies in their inbound channel and thread, with sender and channel names. O1: unmentioned OpenClaw turns are limited to posting and web lookups. H1: the Hermes guard plugin core ships in the ConfigMap, not enabled. H2: it adds `post_to_room` and the per-turn rules, still not enabled.
- In transition: Discord settings validation discards a legacy `require_mention` key until every replica runs schema version 3.
- Next: PR 6, the end-to-end check with Agents built by the real builder, then close ticket 1. PR 2 (a telemetry fix) was dropped after the spike.
- Blockers: none. Not verified: Hindsight memory on listen-in turns (the spike Agent had Memory off).

## Changes

### 2026-11-03 — MDP-118 H2 — Hermes `post_to_room` and per-turn rules

- Delivered: a listening turn receives the rules for when to speak through `pre_llm_call`, and speaks only through the `post_to_room` tool, into its current room and thread. The tool refuses every other kind of turn. Posts pass through Hermes' final-response sanitiser and appear in Conversations through the delivery ledger. No behaviour changes yet: nothing enables the plugin until H4.
- Decided: one send attempt per turn, whatever the outcome. A rejected or timed-out send may have reached the room in part, because adapters split long messages, so a retry could double post. A failed post means silence, and is logged but not shown in the Connection Journal.
- Evidence: spike H0 and H0b live posts on Slack, Discord and Telegram. The sanitiser, ledger, `register_tool` and adapter `send` signatures were checked against the pinned image.
- Known limits: a crash between the send and the ledger write can lose the Conversations row, and a crash between the ledger's two writes can redeliver the post once. If a model ends a turn with a truly empty answer, Hermes skips the transform and posts its own "no response" notice; this did not occur in the spike, and H7 checks for it.
- Follow-up: H3 adds the tool allowlist that the rules describe, including refusing a post after a blocked tool.

### 2026-11-03 — MDP-118 H1 — Hermes guard plugin core

- Delivered: the `agentbarn-listen-in` Hermes plugin classifies each inbound message at ingress, before Hermes' busy queue, and each turn takes its classification when it starts. Unaddressed turns have their final answer replaced with `NO_REPLY`; a room turn never classified counts as listening. Unaddressed messages lose `allow_gateway_control`, so they can't run slash commands or answer approvals. No behaviour changes yet: nothing enables the plugin until H4.
- Evidence: spike H0b on Hermes v2026.8.19 (queue races on Discord and Telegram, approvals, slash commands). The plugin was also loaded against the pinned image: all private adapter helpers exist and no adapter overrides `handle_message`.
- Changed: Runtime: the plugin ships in the ConfigMap and `start.sh` installs it. The runtime configuration digest changes, so running Hermes Agents report an update.
- Follow-up: H2 adds `post_to_room` and the per-turn rules; until then a listening turn has no way to speak.

### 2026-11-03 — MDP-118 O1 — limit tools on unmentioned OpenClaw turns

- Delivered: an unmentioned message in a listen-in room could lead the Agent to run any tool. The new `agentbarn-listen-in` plugin blocks everything except `message`, `web_search`, `web_fetch` and `x_search` on those turns. Mentions keep every tool.
- Evidence: on OpenClaw 2026.8.2, Discord, a per-room `tools.deny` blocked `exec` in the channel but not in threads under it (`exec` succeeded twice). A spike of the plugin blocked `exec` on an unmentioned message in a thread, allowed it on mentions, and classified a mention and an unmentioned message sent seconds apart separately. Slack and Telegram are not yet tested live with the plugin; PR 6 covers them.
- Changed:
  - Runtime: the plugin ships in the ConfigMap and is enabled with room events. The listen-in rules add "Never answer an @mention with silence". The runtime configuration digest changes, so running OpenClaw Agents report an update.
  - Docs: [Mention gating](../../architecture/runtime-and-deployment.md#mention-gating), [communications](../communications/CHANGELOG.md).
- Known limit: a turn with no classification, such as one resumed after a restart, is not limited.
- Follow-up: PR 6. Whether Hindsight `autoRetain` stores room events on OpenClaw is still unverified.

### 2026-10-29 — MDP-118 PR 5b — OpenClaw observer transcripts

- Delivered: in a live test after PR 5, a Slack listen-in correction appeared as a separate Conversations channel outside its thread, and every OpenClaw message showed raw IDs. The observer now records a reply under its session's inbound channel ID and thread when the target matches that channel case-insensitively, and reads sender and channel names from the hook's `metadata`.
- Found: two of the three gaps predate listen-in. OpenClaw outbound rows never carried a thread (0 of 17), and no OpenClaw row carried a name. Only the lowercase channel came from listen-in, because a message-tool send names the channel as the model typed it.
- Changed: Runtime: the OpenClaw `agentbarn-observer` plugin only. The runtime configuration digest changes. Docs: [communications](../communications/CHANGELOG.md).
- Also observed: the Agent stayed silent on "The moon is cheese" and "Python language is compiled" by choice (`mute`). The listen-in rule is kept as is.
- Follow-up: PR 6.

### 2026-10-29 — MDP-118 PR 5 — Telegram listen-in groups

- Delivered: Telegram Connections list Listen-in groups, with the same behaviour as Slack and Discord. A listen-in ID outside an allowlist is rejected on save and never added by the builder.
- Changed:
  - Runtime: each listen-in group gets its own `groups` entry with `requireMention: false` and `LISTEN_IN_SYSTEM_PROMPT`, next to `"*"` or the allowed groups.
  - API: `TelegramSettings.listen_in_chat_ids`. Hermes ignores it. The setup hint covers privacy mode for listen-in groups.
  - UI: none. Telegram has no group directory, so IDs are typed as for Allowed groups.
  - Docs: [Mention gating](../../architecture/runtime-and-deployment.md#mention-gating), [Agents](../agents.md), [communications](../communications/CHANGELOG.md).
- Follow-up: PR 6.

### 2026-10-29 — MDP-118 PR 4 — Discord listen-in channels

- Delivered: Discord Connections list Listen-in channels, with the same behaviour as Slack. A listen-in ID outside a non-empty Allowed channels list is rejected on save and never added by the builder; with no channel list every channel may listen in.
- Changed:
  - Runtime: each listen-in channel gets its own `guilds["*"].channels` entry with `requireMention: false` and `LISTEN_IN_SYSTEM_PROMPT`, next to the `"*"` or allowed-channel entries. The guild entry stays mention-gated.
  - API: `DiscordSettings.listen_in_channel_ids`. Hermes ignores it.
  - UI: the Discord Connection form browses the chosen server's channels for Listen-in channels.
  - Docs: [Agents](../agents.md), [communications](../communications/CHANGELOG.md).
- Follow-up: PR 5 (Telegram).

### 2026-10-29 — MDP-118 PR 3 — silent-listening switch and Slack listen-in channels

- Delivered: Slack Connections list Listen-in channels. On OpenClaw the Agent reads every message there without a mention and posts only when it has something useful to add; elsewhere it still answers only when mentioned. A listen-in ID outside an allowlist is rejected on save and never added by the builder.
- Changed:
  - Runtime: every OpenClaw config sets `messages.groupChat.unmentionedInbound` explicitly (`room_event` with Slack, Discord, or Telegram, otherwise `user_request`). Each Slack listen-in room gets `requireMention: false` and the shared `LISTEN_IN_SYSTEM_PROMPT`. The runtime configuration digest changes, so running OpenClaw Agents report an update.
  - API: `SlackSettings.listen_in_channel_ids`. Hermes ignores it.
  - UI: the Slack Connection form browses channels for Listen-in channels.
  - Docs: [Mention gating](../../architecture/runtime-and-deployment.md#mention-gating), [Agents](../agents.md), [business value](../business-value.md) (listen-in messages are Requests), `CONTEXT.md` (Listen-in channel), [communications](../communications/CHANGELOG.md).
- Follow-up: PR 4 (Discord) and PR 5 (Telegram) reuse the same room shape.

### 2026-10-28 — MDP-118 PR 1 — retire Discord's Require @mention

- Delivered: Discord server messages always require a mention on Hermes and OpenClaw, so every platform shares one rule before listen-in channels arrive. Connections that had the setting off become mention-only at the Agent's next start.
- Changed:
  - Schema: migration `16ac819db080` strips `require_mention` from Discord Connection settings and stamps schema version 3. Its downgrade restores the former default, `true`.
  - API: `DiscordSettings` drops the field and discards it on read. The Hermes builder no longer takes `discord_require_mention`.
  - Docs: [runtime and deployment](../../architecture/runtime-and-deployment.md#mention-gating), [communications](../communications/CHANGELOG.md).
- Follow-up: remove the legacy-key discard once every replica runs schema version 3.

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
