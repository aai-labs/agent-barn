# Personas are Hermes profiles in one pod, not a security boundary

Status: Accepted
Date: 2026-11-04
Origin: AF-425, decisions taken with the maintainer while planning it, and a runtime spike against Hermes `v2026.8.19` on 2026-11-04

Customers want several identities, such as Sales or Lawyer, behind one Agent without another bot install for each. The research draft placed a router above the Runtimes. The maintainer chose to keep one Agent as one pod instead, with one gateway, so a Persona needs no new Kubernetes workload.

## Decision

- **A Persona is a Hermes profile** at `/opt/data/profiles/<key>/`, served by the Agent's one gateway process in Hermes's multiplex mode and addressed over HTTP as `/p/<key>/`. No plugin is involved. The Default Persona is the Agent itself and has no row.
- **Isolation is soft.** Personas share the pod, filesystem and keys. Separation of identity, sessions and built-in memory is configuration. Hard isolation, or different accounts for one provider, means a separate Agent.
- **The Agent keeps one Template pin; a Persona owns only its identity.** SOUL and IDENTITY are versioned per Persona, and everything else in the Template is shared. Pinning a Template per Persona was rejected because `agent_skill` allows one version of a Skill per Agent, so two Templates could need versions that clash; because BOOT and HEARTBEAT would run per Persona; and because tweaking one Persona would need a forked Organization Template, since Overrides are Agent-scoped.
- **Multiplex only for Agents with an active Persona.** Multiplex changes how every profile reads secrets, including the Default's, so Agents without Personas keep their boot unchanged.
- **Secrets live in memory-backed files.** Multiplex reads secrets only from each profile's `.env`. Those files symlink to a memory-backed volume holding values already in the pod, so nothing is written to the Agent's volume or Restore Points.
- **"Always" approvals are Agent-wide.** Hermes keeps one process-wide list, so per-Persona grants aren't possible without patching it. A boot step copies the newest-saved list to every profile.

## Consequences

- **A Persona's prompt is not protected from another Persona.** Any Persona with a terminal can read another's files and keys. The terminal user could already read the gateway's environment through `/proc/1/environ`, so the `.env` files add no new access. The spike confirmed this on an unmodified Agent.
- **Web Chat goes first.** Slack, Discord, Teams and Telegram identity is deferred. The Hermes Slack adapter has no per-message sender identity, and one bot token can't be claimed by two profiles.
- **Tied to the pinned Hermes.** In `v2026.8.19` multiplex is opt-in. Current Hermes documentation says it's on by default and turning it off is retired, so a Hermes upgrade must revisit "multiplex only with Personas".

## Revisit when

- A customer needs Personas isolated from each other, which this design can't provide.
- Hermes is upgraded, or OpenClaw support is added, which would need its own mechanism.
