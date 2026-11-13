# Agent Bots

Not yet available. This is the contract the AF-425 slices implement; delivery state is in the [epic log](agent-bots/CHANGELOG.md), and the decision is in [Bots share their Parent Agent's gateway](../adr/2026-11-05-bots-share-their-parent-agents-gateway.md).

A **Bot** is a full Agent created from its **Parent Agent**'s page. It has its own Template, Skills, Agent Secrets, Communication Connections, Configured Model, LiteLLM key and spend limit, Agent Memory, sessions and Agent Access. It runs as a Hermes profile in its Parent Agent's pod, so creating a Bot never adds a pod.

## Rules

- Hermes only. A Parent Agent and its Bots are all Hermes Agents; OpenClaw is refused with 400.
- One level. A Bot cannot have Bots, and a Parent Agent is never itself a Bot.
- A Bot belongs to its Parent Agent's Organization, and its parent link never changes.
- At most 5 Bots per Parent Agent. Each Bot counts toward the Organization's Agent limit, so an Organization limited to one Agent cannot add Bots.
- The Parent Agent is the first bot: it keeps its own profile, Template and Connections.
- Bots appear only inside their Parent Agent. Home and Agent lists show Parent Agents; a Bot keeps its own Agent id and URL.

## Lifecycle

The pod belongs to the Parent Agent.

- Start, stop, restart, Agent Size, image updates and Restore Points act on the Parent Agent and are refused on a Bot. There is no way to stop one Bot.
- A Bot's status mirrors its Parent Agent's, except that a Bot whose own setup fails is in error while the others run.
- Changing a Bot restarts the Parent Agent and all its Bots (Apply & Restart).
- Deleting a Bot takes effect at the Parent Agent's next restart. Deleting the Parent Agent deletes its Bots.
- Every start issues each Bot fresh runtime keys. The LiteLLM key is created once per Agent and kept across starts.
- A Bot whose runtime material is missing at start is not served, and none of its helpers run. Nothing falls back to the Parent Agent's identity.

## What Bots share

Bots have separate configuration and state, not enforced isolation. Everything below is shared by the Parent Agent and all its Bots:

- **Trust boundary.** Every Bot runs as the same user in the same process. A Bot's terminal can read its siblings' `.env` files and the pod's environment, and a prompt injection reaching one Bot can reach every Bot's credentials. Per-Bot Agent Access controls what people see in Agent Barn, not what a Bot can reach. Bots that must keep secrets from each other's users must be separate Agents.
- The working directory `/workspace`, the terminal shell environment, and "always" command approvals.
- The turn limit, set on the Parent Agent and shown read-only on Bots.
- Command approval: either every Bot uses Manual, or none does.
- The run cap of 10 concurrent runs; beyond it a delivery fails.
- Volume, CPU, memory, image, logs, and crashes.

Each Bot keeps its own SOUL and instructions, sessions, built-in memory, model and LiteLLM key, scheduled jobs, Tasks, plugin identity, and Agent Barn keys, and its terminal sees its own integration credentials and Agent Barn identity.

## Messaging

- Each Bot has its own bot installs: its own Slack app and its own Telegram bot.
- A Parent Agent and its Bots can connect the same platform, each with its own app or bot. The one refused pair is Agent Barn Telegram on the Parent Agent with a Bot's own Telegram, because Agent Barn Telegram sets `TELEGRAM_WEBHOOK_URL` for the whole process.
- Bots support Slack, Telegram, Discord and Web Chat. Microsoft Teams and Agent Barn Telegram are refused on Bots.
- A Bot's scheduled jobs and webhook results are delivered from the Bot's own account on its own platform.

## Operations

- Logs, diagnostics, resource usage, Restore Points and File Sync belong to the Parent Agent and cover every Bot. Logs cannot be split per Bot.
- A Parent Agent's Restore Point captures every Bot's sessions, memory and scheduled jobs, but not its secrets or generated files. A Bot's database row isn't rolled back: a Bot deleted after the capture stays deleted and its restored files are removed at the next start, and a Bot created after the capture starts with no history.
- A Bot's tool calls, activity, costs, conversations and memory are its own.
- Health shows the Parent Agent's pod, and for each Bot whether the pod is serving it.

## Access

- A Bot's effective access is its own grants plus its Parent Agent's grants. Bot grants only add.
- A Member can be given access to a Bot only if they can read its Parent Agent.
- Creating a Bot needs `agent.create` in the Organization and `agent.update` on the Parent Agent. Restarting needs `agent.lifecycle.manage` on the Parent Agent.

## UI

- Opening an Agent shows the Parent Agent. A switcher in the path bar (`Organization / Parent Agent / Bot`) lists the Parent Agent, its Bots with their status, and New bot. Switching keeps the current tab.
- Bot pages show the Bot's own Overview, Chat, Conversations, Tasks, Memory, Tool calls, Artifacts, Playbooks, Activity, Costs and settings.
- An "Agent" menu group holds Logs, Resource usage, File sync, Restore points and Size, and always acts on the Parent Agent.
- Home shows the Parent Agent with its Bot count.
- The UI states that Bots share one trust boundary wherever Bots are created or shared.

## Hermes upgrades

Bots rely on Hermes multiplex behaviour pinned to `v2026.8.19`: profiles served by one gateway, per-profile secret scope, terminal passthrough, and scheduled-job delivery. Rerun the image-level Bot tests on every Hermes upgrade.
