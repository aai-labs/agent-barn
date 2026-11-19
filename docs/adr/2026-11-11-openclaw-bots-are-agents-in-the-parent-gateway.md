# OpenClaw Bots are agents in their Parent Agent's gateway

Status: Accepted
Date: 2026-11-11
Origin: AF-445, maintainer decisions on 2026-11-11; runtime spike on 2026-11-11 against OpenClaw `2026.8.2`

This extends [Bots share their Parent Agent's gateway](2026-11-05-bots-share-their-parent-agents-gateway.md) to OpenClaw. A Bot of an OpenClaw Parent Agent is an OpenClaw agent in the Parent Agent's one gateway, with its own workspace, sessions, model provider and channel accounts, because OpenClaw serves several agents and several accounts per platform from one process. A Parent Agent and its Bots share a runtime, and a Parent Agent without Bots keeps its single-agent configuration.

## Decisions

- **Memory tool only.** The Hindsight plugin holds one token and one client per process, so automatic recall and retain can serve only one Agent's bank. The maintainer chose to keep them for the Parent Agent, exclude Bot sessions from its bank, and give each Bot its Agent Memory through the memory tool under its own key.
- **Shared Firecrawl.** Firecrawl and the web tools are configured once per process. The maintainer chose to let Bots use the Parent Agent's setup and to refuse a Bot's own Firecrawl credential.
- **The Parent Agent moves to its own `default` account** on every platform once it has a Bot. In OpenClaw, a named account inherits the platform's root policies, so a Bot account beside root-level parent settings would admit the Parent Agent's allowlists.

## Consequences

- Every trust-boundary consequence of the Hermes design applies: one user and one process, so any agent's commands can read every Bot's mounted credentials.
- Turning a single-agent configuration into a multi-agent one changes the gateway's model names and session keys. The Parent Agent's existing sessions continue under `agent:main:…`, and removing the last Bot must clean the multi-agent settings out of `openclaw.json`.
- The design depends on OpenClaw multi-agent behaviour pinned to `2026.8.2`. Every OpenClaw upgrade must rerun the image-level Bot tests before release.

## Revisit when

- The Hindsight plugin can hold a token per agent, which would allow automatic memory per Bot.
- An OpenClaw upgrade changes agent ownership, channel accounts, file secret references, or the `before_tool_call` hook.
