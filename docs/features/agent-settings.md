# Agent Settings

## Read when

Read before changing the Organization-scoped default runtime model, the relationship between an Agent's model and its Organization's default, the model allowlist invariant, or the surface where owners manage Agent defaults.

## Role in the system

Agent Settings holds Organization-scoped defaults that Agents follow unless they override them. Runtime model is the first and currently only setting. The domain exists so that a default can be changed once and take effect across every Agent that inherits it, instead of being copied into each Agent at creation time where it can never be moved again.

An Agent Setting is resolved, never snapshotted. That single decision is what the rest of this document describes.

## Invariants

- One `organization_agent_settings` row per Organization, created lazily on first write. A missing row and an all-NULL row mean the same thing, so an Organization that has never opened Agent Settings needs no row.
- Every setting column is nullable, and NULL means "follow the platform value". `default_model IS NULL` resolves to `AGENT_DEFAULT_MODEL`, so an Organization that never picks a default follows platform model upgrades rather than freezing whatever was configured on the day it was created.
- An Agent's `model` column keeps the empty string as its inherit sentinel. The column is non-nullable; clearing an override writes `""`, never NULL.
- Model resolution is two indirections deep and both are read at Agent start:
  - `effective_model(agent) = agent.model or effective_default_model(org)`
  - `effective_default_model(org) = org_settings.default_model or Config.agent_default_model`
- An Organization's **own** default must be a member of its `allowed_models`. This is enforced at both ends: setting a default validates it against the allowlist, and editing the allowlist rejects a list that no longer permits the current default. An Agent that inherits therefore never runs a model its Organization disallows.
- A candidate default is additionally checked against the live OpenRouter catalogue, because the allowlist stores globs and an Organization on `["*"]` would otherwise accept any string. That check is advisory: an unreachable catalogue logs and proceeds, matching how the allowlist editor already degrades.
- The allowlist invariant cannot be stated about an Organization that follows the platform default. That value changes on a deploy, with no request to this API in which to validate or repair anything. An inheriting Agent of such an Organization therefore starts on the platform default whatever the allowlist says; the start-time allowlist re-check applies only to Agents carrying an explicit override.
- Reading and writing Agent Settings requires the Organization Permission `organization.update` — fixed Owner and Admin roles. An Organization Member is refused with 403.
- Changing a default emits `organization.agent_settings.changed` through the Domain Events outbox to the security-audit projection. Saving an unchanged value emits nothing.
- Changing a default never restarts an Agent. A running Agent keeps serving the model baked into its ConfigMap at start and picks the new default up on its next start, consistent with the rest of the Agent configuration surface where restarts stay explicit.
- Because of that, an Agent has two distinct model facts and a surface must not confuse them: `effective_model` is what it *would* start on now, while `running_model` records what its pod actually started on. `start_agent` writes the latter and `stop_agent` clears it; `pending_model` is set only when the two disagree, which is what lets a running Agent be shown as still serving the old model. Nothing recomputes this from Kubernetes — the runtime merges its config once at container start and never re-reads it.
- Agent counts exposed alongside the setting cover every non-deleted Agent in the Organization, not only those visible to the caller. They state how far a change reaches; they do not name Agents.

## Primary flows

### Read

`GET /organizations/{organization_id}/agent-settings` returns the Organization's own choice, the resolved effective value, which of the two it came from, and the split of Agents that inherit versus override. The resolved value is what lets a client show "Use organization default — GLM 5.2" without a second request.

### Change

`PUT /organizations/{organization_id}/agent-settings` sets or clears `default_model`. An explicit `null` reverts to following the platform default; omitting the field leaves the stored value alone, which is what keeps the DTO usable once further settings live beside this one. Persisting the value and staging its Event share one session and one commit, so a settings change is never visible without its audit record.

### Effect on Agents

Nothing is written to any Agent. The next `start_agent` for an inheriting Agent resolves the new default and renders it into the runtime configuration. Agents with an explicit `model` are untouched at every step.

## Boundaries

Agent Settings owns the stored defaults and their validation. Agents own `Agent.model`, the resolution call at start, and the inherit/override contract on the Agent read model. Organizations own `allowed_models` and enforce the invariant on the allowlist side. `AgentSettingsLookupService` is the read-only seam other domains use, so neither Agents nor Organizations depends on `AgentSettingsService`.

A platform-administered layer of defaults does not exist. If one is added, it belongs behind `resolve_default_model` as a third fallback, not as a new resolution path.

## Source map

| Concern                                   | Authoritative source                                        |
| ----------------------------------------- | ----------------------------------------------------------- |
| Persistence and request/read contracts    | `../../api/domains/agent_settings/models.py`                |
| Validation, authority, and Event emission | `../../api/domains/agent_settings/service.py`               |
| Transaction boundary and outbox staging   | `../../api/domains/agent_settings/repository.py`             |
| Cross-domain resolution seam              | `../../api/domains/agent_settings/lookup.py`                 |
| HTTP routes                               | `../../api/domains/agent_settings/routes.py`                 |
| Model resolution at Agent start           | `../../api/domains/agents/service.py`                       |
| Running vs pending model on the read model | `../../api/domains/agents/service.py`, `../../ui/src/features/agents/components/pending-model-note.tsx` |
| Inherit/override on the Agent read model  | `../../api/domains/agents/models.py`                        |
| Inherit/override Agent counts             | `../../api/domains/agents/repository.py`                    |
| Allowlist side of the invariant           | `../../api/domains/organizations/service.py`                |
| Event name, payload, and audit support    | `../../api/domains/events/catalog.py`, `../../api/domains/events/security_audit.py` |
| UI contracts and hooks                    | `../../ui/src/features/agent-settings/schemas.ts`, `../../ui/src/features/agent-settings/hooks/` |
| Owner-facing surface                      | `../../ui/src/features/agent-settings/components/`, `../../ui/src/app/dashboard/[orgId]/settings/page.tsx` |
| Shared settings shell                     | `../../ui/src/components/settings/`                          |
| Agent-side inherit/override controls      | `../../ui/src/features/agents/components/model-choice.tsx`, `../../ui/src/features/agents/components/model-source-badge.tsx` |
| Integration coverage                      | `../../api/tests/integration/test_agent_settings.py`, `../../ui/tests/e2e/settings-agent-defaults.spec.ts` |

## Related decisions

- [`2026-08-19-organization-scoped-agent-settings.md`](../adr/2026-08-19-organization-scoped-agent-settings.md)

## Change impact

Adding a setting affects the table, both DTOs, the resolver, whichever domain consumes it, the change Event payload, and this document's invariants. Changing how the default resolves affects Agent start, the model picker endpoint, the Agent read model, and the allowlist invariant on both sides — the allowlist and the default are one contract, so neither can be changed alone. Changing the authority gate affects the routes, the Organization Permission catalogue, and the 403 expectations in the integration tests.
