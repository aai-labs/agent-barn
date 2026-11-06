# Bots share their Parent Agent's gateway

Status: Accepted
Date: 2026-11-05
Origin: AF-425, maintainer decision on 2026-11-05 that bots share only the gateway; runtime spike on 2026-11-06

A Bot is a full Agent created inside a Parent Agent. It runs as a Hermes profile in the Parent Agent's one pod and one `hermes gateway run` process, rather than in a pod of its own. This is the maintainer's design for AF-425: bots share the gateway and keep their own configuration and state, so the pod count equals the number of Parent Agents however many Bots they hold.

## Considered alternatives

- **Personas inside one Agent**, sharing the Agent's Template, model, secrets and Connections, were built and then replaced: they shared far more than the gateway.
- **Each bot a separate Agent with its own pod** is today's model. It keeps a real isolation boundary, at one pod per bot.

## Consequences

- A Bot is not a security boundary. Every Bot runs as the same user in the same process, so a Bot's terminal can read its siblings' `.env` files and the pod's environment. Per-Bot Agent Access controls what people see in Agent Barn, not what a Bot can reach inside the pod. Bots that must hold secrets from each other's users need separate Agents.
- Bots also share the working directory, the terminal shell environment, "always" command approvals, the turn limit, the run cap of 10 concurrent runs, the volume, CPU, memory and image, and crashes.
- Lifecycle belongs to the pod: start, stop, restart, Agent Size, image updates, Restore Points, logs and resource usage act on the Parent Agent. Changing a Bot restarts the Parent Agent and all its Bots.
- A Parent Agent and its Bots must not share a messaging platform. In the spike, a Bot's scheduled message on a platform its Parent Agent also used was sent through the Parent Agent's connection. Without that overlap, the Bot's scheduled and webhook results were delivered from the Bot's own account.
- The design depends on Hermes multiplex internals pinned to `v2026.8.19`. Every Hermes upgrade must rerun the image-level Bot tests before release; newer Hermes documentation already describes multiplex differently.

## Revisit when

- Bots need to be isolated from each other, which needs either separate pods or a Hermes change giving each profile its own user, working directory and shell.
- A Hermes upgrade changes multiplex, secret scoping or scheduled-job delivery.
