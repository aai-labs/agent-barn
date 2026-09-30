# Organization-scoped Agent Settings resolve, and the default model is always runnable

Status: Accepted
Date: 2026-08-19
Origin: [AF-225](https://aai-labs.atlassian.net/browse/AF-225)

Agent defaults live in a dedicated `organization_agent_settings` table, one row per Organization, with every setting stored as a typed nullable column where NULL means "follow the platform value". Defaults are **resolved on read**, never snapshotted onto the Agent, so changing an Organization's default moves every Agent that inherits it and leaves explicit overrides alone. An Organization's own default is held inside its model allowlist by enforcement at both ends; the platform default it may instead be following is exempt from that invariant, because nothing in an API request can guarantee a value a deploy controls.

## Considered alternatives

- **Keep the default as `AGENT_DEFAULT_MODEL` only** — rejected because changing it requires a Helm value edit and an API redeploy, applies to every Organization on the install, and leaves no audit trail. It remains as the install-wide floor, not as the management surface.
- **More nullable columns on `organization`** — rejected. The ticket's stated purpose is that later settings (approval mode, runtime, platform, tool policy, budgets) arrive without reworking the concept; a dedicated aggregate keeps them out of the Organization identity row and gives each its own change Event.
- **A JSONB `settings` blob** — rejected. It gives up typed validation and per-field auditing, which is precisely what an owner-facing policy surface needs.
- **Snapshot the platform default into each Organization at creation** — rejected because it is what produced the original defect: every Organization froze the value current on its creation day, so no platform model upgrade ever reached anyone, and the seeded allowlist silently drifted out of agreement with the running default.
- **Copy the resolved default onto `Agent.model` at creation** — rejected for the same reason at Agent granularity. It is what the UI effectively did, and it is why "change the default" moved nothing.
- **Make `Agent.model` nullable to express inheritance** — rejected. The empty string already carried that meaning and `start_agent` already resolved it; a nullable column buys nothing and touches every read path on a hot table.
- **Let the default bypass the allowlist entirely** — rejected as too broad. It fixes the start failures but abandons a useful invariant: an owner should not be able to point every inheriting Agent at a model the Organization has explicitly disallowed. The narrower exemption below keeps the invariant everywhere an Organization actually has control.
- **Enforce the allowlist invariant with no exemption at all** — rejected because it reintroduces the failure this ticket set out to remove. An Organization following the platform default cannot be asked to keep its allowlist in step with a value that changes on deploy.
- **Auto-restart running Agents when the default changes** — rejected. The model is baked into the pod's ConfigMap at start, and the Agent configuration surface deliberately keeps restarts explicit. A settings dropdown that restarts an Organization's whole fleet is a larger blast radius than this decision should own.

## Consequences

- Two indirections are read at every Agent start and on every Agent read DTO. Reads that build many Agent DTOs must resolve the default once per request and pass it down; resolving per row is one query per row.
- The allowlist and the default are one contract. Neither `OrganizationService.update_organization` nor `AgentSettingsService.update_settings` can be changed without checking the other, and `OrganizationService` therefore depends on the Agent Settings read seam.
- The start-time allowlist re-check now distinguishes inherited from overridden models. An Agent inheriting a platform default its Organization's allowlist excludes will start; this is deliberate, and it is the behaviour the regression test pins.
- Cross-domain access goes through `AgentSettingsLookupService`, a read-only module importing only its repository and config. Both Agents and Organizations inject it; neither may depend on `AgentSettingsService`.
- A new Domain Event, `organization.agent_settings.changed`, carries the setting name with both its before and after values. Unlike the allowlist event it can afford both, because a setting is a bounded scalar rather than an unbounded list.
- Adding a setting is a column, a DTO field, a validation rule, and an Event payload field — not a schema redesign. That is the property this structure was chosen to have.

## Revisit when

Revisit this decision if platform administrators need to manage defaults centrally (which belongs behind `resolve_default_model` as a third fallback, not as a new resolution path), if a setting appears that cannot be expressed as a bounded scalar column, if defaults need to apply at a scope between Organization and Agent such as a team or an Agent group, or if a default change is ever required to take effect on already-running Agents.
