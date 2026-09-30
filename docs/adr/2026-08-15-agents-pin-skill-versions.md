# Agents pin exact skill versions like template pins

Status: Accepted
Date: 2026-08-15

An agent's skill assignments pin an explicit skill version at apply time, mirroring how agents pin an exact template version. Publishing a newer skill version never moves an existing pin, and recovering from a bad skill version means re-pinning the agent to an older version.

## Context

Skills were assigned to agents as lineages only: each agent mounted the skill's *latest* version at start, and there was no way to choose a different version. The only recovery path for a bad published version was "restore as draft" — a global, lineage-level operation that republished old content. That was wrong for two reasons: recovering from a bad version is a per-agent decision (an agent should pin whatever version suits it, independently of what the org publishes next), and the version-deletion feature made the "restore" provenance redundant.

## Decision

- Add `agent_skill.pinned_version` (explicit, backfilled to each skill's then-latest at migration) so every assignment records the exact version the agent mounts at start.
- `AgentCreate`/`AgentUpdate` accept optional `skill_versions` (`{skill_id, version}`). Skills without a pin resolve to their latest at apply time; a pin must reference a version that exists, and only skills the agent ends up with can be pinned.
- Start-time mounting loads each assigned skill's pinned-version files; implicitly auto-attached aai-cli skills still resolve to latest.
- A skill version pinned by any agent cannot be deleted (409). Re-pin the agent first; deletion never silently changes what an agent mounts.
- The agent configuration Skills section exposes a version selector per assigned skill; applying a change sends `skill_versions`.

## Consequences

- New publishes no longer reach assigned agents automatically — they pin, and re-pinning is an explicit apply (like template versions).
- Recovering from a bad skill version is now a per-agent, non-destructive re-pin; no history is rewritten.
- Version deletion is safe from dangling pins because pinned versions are protected.
- Existing assignments were backfilled to their then-latest, so no agent silently changes at deploy.
