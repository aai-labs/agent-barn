# Agent Context Map

Use this index to load only the context required by the task. `../AGENTS.md` remains the source of mandatory repository-wide rules, and `../CONTEXT.md` remains the source of domain terminology.

## Engineering guidance

| When working on                                        | Read                                                   |
| ------------------------------------------------------ | ------------------------------------------------------ |
| API code and domain implementation                     | [`guidelines/code.md`](guidelines/code.md)             |
| UI code and frontend data flow                         | [`guidelines/webapp.md`](guidelines/webapp.md)         |
| Tests and verification                                 | [`guidelines/testing.md`](guidelines/testing.md)       |
| Multi-ticket or multi-PR epic coordination             | [`guidelines/epics.md`](guidelines/epics.md)           |
| Local development, migrations, deployment, or releases | [`guidelines/operations.md`](guidelines/operations.md) |

## System context

| When working on                                                     | Read first                                                                         | Then inspect                                                                                        |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Cross-domain changes or a new domain                                | [`architecture/system-map.md`](architecture/system-map.md)                         | `../api/api_app.py`, target domain directories                                                         |
| API routes, services, repositories, DI, migrations, or API tests    | [`architecture/api.md`](architecture/api.md)                                       | `../api/`, `../api/tests/`                                                                                |
| App Router pages, providers, queries, mutations, or Playwright      | [`architecture/ui.md`](architecture/ui.md)                                         | `../ui/src/`, `../ui/tests/`                                                                              |
| Agent lifecycle, chat platform, model, or runtime selection         | [`features/agents.md`](features/agents.md)                                         | `../api/domains/agents/`, `../ui/src/features/agents/`                                                    |
| Organization-scoped Agent defaults, the default runtime model, or the model allowlist invariant | [`features/agent-settings.md`](features/agent-settings.md) | `../api/domains/agent_settings/`, `../ui/src/features/agent-settings/` |
| AF-253 Agent Config Tuning delivery state                           | [`features/af-253-agent-config-tuning/CHANGELOG.md`](features/af-253-agent-config-tuning/CHANGELOG.md) | Agent configuration, override activation, history, and source-update slices |
| Runtime builders, Kubernetes agent resources, or service deployment | [`architecture/runtime-and-deployment.md`](architecture/runtime-and-deployment.md) | `../api/domains/agents/builders/`, `../helm/`, `../.github/workflows/`                                       |
| Templates, template versions, required skills, or skill archives    | [`features/templates-and-skills.md`](features/templates-and-skills.md)             | `../api/domains/templates/`, `../api/domains/skills/`, `../ui/src/features/platform-templates/`               |
| Login, tokens, users, organizations, membership, or tenancy         | [`features/identity-and-organizations.md`](features/identity-and-organizations.md) | `../api/domains/auth/`, `../api/domains/users/`, `../api/domains/organizations/`                             |
| Active AF-235 platform-administration delivery state                 | [`features/platform-administration/CHANGELOG.md`](features/platform-administration/CHANGELOG.md) | Identity, Domain Events, related ADRs, and `../docs/plans/AF-235-remaining-platform-management-tasks.md` |
| Fixed Organization Roles, Permissions, Agent Access Roles, or Agent assignments | [`features/rbac/IMPLEMENTATION-BRIEF.md`](features/rbac/IMPLEMENTATION-BRIEF.md) | [`adr/2026-07-21-separate-organization-and-agent-access-roles.md`](adr/2026-07-21-separate-organization-and-agent-access-roles.md), identity/Agent features, authorization and Agent repositories |
| Any new or changed endpoint, service method, or repository query that reads or writes an Agent or a subordinate resource (conversations, tool calls, activity, logs, costs, Secrets, Skills, config) | [`features/rbac/IMPLEMENTATION-BRIEF.md`](features/rbac/IMPLEMENTATION-BRIEF.md) | Authorization service, target repository's visibility query |
| Conversation history, tool-call audit, parsers, or telemetry ingest | [`features/activity-and-ingest.md`](features/activity-and-ingest.md)               | `../api/ingest_app.py`, `../api/domains/conversations/`, `../api/domains/tool_calls/`, `../api/domains/ingest/` |
| Internal Domain Events, Outbox Messages, Event Deliveries, Event Handlers, audit projections, or the platform Event Delivery Monitor | [`features/domain-events.md`](features/domain-events.md) | `../api/domains/events/`, event-producing domain repositories, `../api/migrations/versions/`, `../ui/src/features/event-deliveries/` |
| Cost records, the cost sync/healing CronJob, spend attribution, or either Costs page | [`features/costs.md`](features/costs.md)                                           | `../api/domains/costs/`, `../ui/src/features/costs/`, `../helm/agentbarn-api/templates/cost-sync-cronjob.yaml`, `../docs/plans/AF-281-cost-tracking-findings.md` |
| External provider credentials, Slack setup, or Google OAuth         | [`features/integrations.md`](features/integrations.md)                             | `../api/domains/integrations/`, agent secret code                                                      |
| Communication Connections, Platform Plugins, or gateway delivery    | [`features/communications/CHANGELOG.md`](features/communications/CHANGELOG.md)     | `../api/domains/communications/`, runtime communication adapters                                       |
| Shared credentials (org-scoped reusable credentials)               | [`features/integrations.md`](features/integrations.md)                             | `../api/domains/shared_credentials/`                                                                   |
| Architectural rationale or revisiting an accepted decision          | [`adr/README.md`](adr/README.md)                                                   | Related feature or architecture document                                                            |
| Domain terminology                                                  | [`../CONTEXT.md`](../CONTEXT.md)                                                   | Relevant feature document                                                                           |

## Maintenance

Update this map in the same change when a routed document, API domain, UI feature, runtime, or major responsibility is added, removed, renamed, or moved. Update the relevant feature or architecture document when its invariants, boundaries, state model, or change-impact surface changes.
