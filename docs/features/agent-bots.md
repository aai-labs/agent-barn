# Agent Bots

Not yet available. This is the contract the AF-425 (Hermes) and AF-445 (OpenClaw) slices implement; delivery state is in the [epic log](agent-bots/CHANGELOG.md). The decisions are in [Bots share their Parent Agent's gateway](../adr/2026-11-05-bots-share-their-parent-agents-gateway.md) and [OpenClaw Bots are agents in their Parent Agent's gateway](../adr/2026-11-11-openclaw-bots-are-agents-in-the-parent-gateway.md).

A **Bot** is a full Agent created from its **Parent Agent**'s page. It has its own Template, Skills, Agent Secrets, Communication Connections, Configured Model, LiteLLM key and spend limit, Agent Memory, sessions and Agent Access. It runs in its Parent Agent's pod, as a Hermes profile or an OpenClaw agent, so creating a Bot never adds a pod.

## Rules

- Same runtime. A Bot takes its Parent Agent's runtime, Hermes or OpenClaw, and a Parent Agent and its Bots never mix runtimes.
- One level. A Bot cannot have Bots, and a Parent Agent is never itself a Bot.
- A Bot belongs to its Parent Agent's Organization, and its parent link never changes.
- At most 5 Bots per Parent Agent. Each Bot counts toward the Organization's Agent limit, so an Organization limited to one Agent cannot add Bots.
- The Parent Agent is the first bot: it keeps its own profile or agent, Template and Connections.
- Bots appear only inside their Parent Agent. Home and Agent lists show Parent Agents; a Bot keeps its own Agent id and URL. `GET /organizations/{organization_id}/agents?include_bots=true` also returns the Bots the caller can read, each with its `parent_agent_id`; the Organization Tasks page uses it to name and filter by Bots.

## Lifecycle

The pod belongs to the Parent Agent.

- Start, stop, restart, Agent Size, image updates and Restore Points act on the Parent Agent and are refused on a Bot. There is no way to stop one Bot.
- A Bot's status mirrors its Parent Agent's, except that a Bot whose own setup fails is in error while the others run.
- Changing a Bot restarts the Parent Agent and all its Bots (Apply & Restart).
- Deleting a Bot takes effect at the Parent Agent's next restart. Deleting the Parent Agent deletes its Bots.
- Every start issues each Bot fresh runtime keys. The LiteLLM key is created once per Agent and kept across starts.
- A Bot whose runtime material is missing at start is not served, and none of its helpers run. Nothing falls back to the Parent Agent's identity or keys.
- On OpenClaw, a Parent Agent's sessions, scheduled jobs and memory carry over when its first Bot is added and when its last Bot is removed.

## What Bots share

Bots have separate configuration and state, not enforced isolation. Everything below is shared by the Parent Agent and all its Bots:

- **Trust boundary.** Every Bot runs as the same user in the same process. A Bot's terminal can read its siblings' credentials (their `.env` files on Hermes, their mounted Bot Secrets on OpenClaw) and the pod's environment, and a prompt injection reaching one Bot can reach every Bot's credentials. Per-Bot Agent Access controls what people see in Agent Barn, not what a Bot can reach. Bots that must keep secrets from each other's users must be separate Agents.
- Volume, CPU, memory, image, logs, and crashes.

On Hermes, Bots also share:

- The working directory `/workspace`, the terminal shell environment, and "always" command approvals.
- The turn limit, set on the Parent Agent and shown read-only on Bots.
- Command approval: either every Bot uses Manual, or none does.
- The run cap of 10 concurrent runs; beyond it a delivery fails.

On OpenClaw, Bots also share:

- Firecrawl and web tool settings. Bots use the Parent Agent's Firecrawl setup and key; a Bot's own Firecrawl credential is refused.
- Automatic memory. Hindsight recall and retain run for the Parent Agent only, and Bot conversations are kept out of the Parent Agent's memory bank.
- The pod's memory limit, which is the Parent Agent's Agent Size and does not grow with Bots. A Parent Agent with two Bots used 890 MiB idle in local testing against the default 1 GiB limit, so a Parent Agent with several Bots may need a larger Agent Size.

Each Bot keeps its own SOUL and instructions, sessions, model and LiteLLM key, scheduled jobs, Tasks, plugin identity, and Agent Barn keys, and its terminal sees its own integration credentials and Agent Barn identity. On Hermes it keeps its own built-in memory. On OpenClaw it keeps its own workspace, and it saves and recalls Agent Memory through the memory tool under its own key.

## Messaging

- Each Bot has its own bot installs: its own Slack app, Telegram bot and Discord bot.
- A Parent Agent and its Bots can connect the same platform, each with its own app or bot. The one refused pair is Agent Barn Telegram on the Parent Agent with a Bot's own Telegram. On Hermes, Agent Barn Telegram sets `TELEGRAM_WEBHOOK_URL` for the whole process; on OpenClaw the pair has not been verified.
- Bots support Slack, Telegram, Discord and Web Chat. Microsoft Teams and Agent Barn Telegram are refused on Bots.
- A Bot's scheduled jobs and webhook results are delivered from the Bot's own account on its own platform. On OpenClaw, the trigger server creates each job owned by its agent and pinned to that agent's account, `default` for the Parent Agent.
- On OpenClaw, when an agent's message or scheduled job names a platform, it is sent from that agent's own account there. It is refused when the agent has no account of its own on that platform or names another agent's account, so no agent posts through another's app or bot. A reply to the current conversation needs no platform and is left as it is.
- On OpenClaw, a Bot can listen in its own rooms. Room events are set per agent, so only the Bot's own unmentioned messages in its rooms become room events, and the gateway's one listen-in guard reads the Bot's own rooms and its Slack history with the Bot's own app; see [runtime and deployment](../architecture/runtime-and-deployment.md).
- On Hermes, a Bot can listen in its own rooms. Its profile gets its own copy of the listen-in guard and its own startup check, the guard reads only the Bot's rooms, classifies only messages on the Bot's own apps and posts through them, and each Bot always carries its own room list in its platform settings, empty when it has none, so it never falls back to the Parent Agent's process-wide rooms.

## How a pod serves Bots

**Hermes** (`v2026.8.19`): each Bot is a profile served by the one `hermes gateway run` process, with its own `.env` and secret scope. Web Chat reaches a Bot through `/p/<bot-id>`, the terminal passes only the profile's own values through, and scheduled jobs deliver through the job profile's own connections (`hermes-base/patch-bot-cron-delivery.py`).

**OpenClaw** (`2026.8.2`): each Bot is an entry in `agents.entries`, keyed by its Agent id, in the one gateway's `openclaw.json`, and the Parent Agent is `main`. A Parent Agent without Bots keeps today's single-agent configuration.

- `agents.ownership` is `explicit` and `main` owns ambient work. Each Bot has its own workspace and agent directory, which hold its sessions and auth store.
- The Parent Agent is reached as `openclaw/main` and a Bot as `openclaw/<bot-id>`; `openclaw/default` stops working once there is a second agent. Session keys name their agent (`agent:<id>:…`), and the Parent Agent's existing sessions continue as `agent:main:…`.
- Each platform holds one account per agent: the Parent Agent's is `default`, and each Bot's is its Agent id. Every account writes all its own policy keys, and every account has a binding to its agent.
- Each Bot has its own model provider, `litellm-bot-<slot>`, whose key comes from a private copy of the Bot's Secret made at boot. Bot keys never enter the gateway environment.
- The `agentbarn-bot-env` plugin sets each command's environment, after every other plugin. A Bot's commands get the values from its own Secret, its own aai-cli config and its own workspace as the artifact upload root, and every other value from the Parent Agent's Secret is blanked. The exceptions are Firecrawl and the in-pod LLM proxy, which are shared. The Parent Agent's commands keep its own values, and neither can be overridden by the model. A command from an agent without a matching Secret is refused, and so is a code-mode command from a Bot.
- Telemetry, the native-channel observer and the health server file each event under the agent it belongs to: the agent id the gateway gives, else the agent named in the session key, else the channel account. A Bot's events are sent with its own ingest key from its Secret; an event whose agent has no Secret is dropped, never filed under the Parent Agent. The health server reports each channel account's connection under its own agent, lists the Bots the pod serves, and records a spent LLM limit for the key that hit it.
- The `agentbarn-tasks` plugin runs the Task command for each agent with that agent's identity and workspace, a Bot's from its own Secret, so each agent records and is shown its own Tasks; see [Agent Tasks](agent-tasks.md).
- Each Bot runs its own communications adapter and trigger server, on port `8100 + slot`, through the one gateway as `openclaw/<bot-id>` with the gateway's token.
- At every start, `init-openclaw.js` replaces the agent entries in the saved `openclaw.json` and removes the multi-agent settings, Bot providers and Bot key references the new config no longer names, so removing the last Bot returns the Parent Agent to one agent. `bot-setup.py` then writes each Bot's workspace and private key file, and removes a Bot it cannot set up from `openclaw.json`. A deleted Bot's files are removed at start and its scheduled jobs once the gateway answers. A scheduled job whose agent no longer exists fails rather than running as another agent.

## Operations

- Logs, diagnostics, resource usage, Restore Points and File Sync belong to the Parent Agent and cover every Bot. Logs cannot be split per Bot.
- A Parent Agent's Restore Point captures every Bot's sessions, memory and scheduled jobs, but not its secrets or generated files. On OpenClaw that keeps each Bot's `agents/<id>` sessions, its own `USER.md` and work in `workspace-<id>`, and its trigger receipts, and leaves out the instructions and skills `bot-setup.py` rewrites and the credential and config folders (`.config`, `.local`, `aai-cli`) in `bots/<id>`. A Bot's database row isn't rolled back: a Bot deleted after the capture stays deleted and its restored files are removed at the next start, and a Bot created after the capture starts with no history.
- A Bot's tool calls, activity, costs, conversations and memory are its own.
- Health shows the Parent Agent's pod, and for each Bot whether the pod is serving it.

## Access

- A Bot's effective access is its own grants plus its Parent Agent's grants. Bot grants only add.
- A Member can be given access to a Bot only if they can read its Parent Agent.
- Creating a Bot needs `agent.create` in the Organization and `agent.update` on the Parent Agent. Restarting needs `agent.lifecycle.manage` on the Parent Agent.

## UI

- Opening an Agent shows the Parent Agent. A switcher in the path bar (`Organization / Parent Agent / Bot`) lists the Parent Agent, its Bots with their status, and New bot. Switching keeps the current tab.
- Bot pages show the Bot's own Overview, Chat, Conversations, Tasks, Memory, Tool calls, Artifacts, Playbooks, Activity, Costs and settings.
- An "Agent" menu group holds Logs, Resource usage, File sync, Restore points and Size, and always acts on the Parent Agent. Every Agent on either runtime shows it, with or without Bots.
- Home shows the Parent Agent with its Bot count.
- The UI states that Bots share one trust boundary wherever Bots are created or shared.
- The UI is the same on both runtimes, except that the New bot dialog and a Bot's settings offer no command approval on OpenClaw.

## Runtime upgrades

Hermes Bots rely on Hermes multiplex behaviour pinned to `v2026.8.19`: profiles served by one gateway, per-profile secret scope, terminal passthrough, and scheduled-job delivery.

OpenClaw Bots rely on OpenClaw multi-agent behaviour pinned to `2026.8.2`: explicit agent ownership, per-agent model selection, channel accounts and bindings, file secret references, the `before_tool_call` hook rewriting command parameters, and scheduled-job ownership and delivery account.

Rerun that runtime's image-level Bot tests on every upgrade.
