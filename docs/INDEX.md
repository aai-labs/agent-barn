# Agent Context Map

Use this index to load only the context required by the task. `AGENTS.md` remains the source of mandatory repository-wide rules, and `CONTEXT.md` remains the source of domain terminology.

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
| Cross-domain changes or a new domain                                | [`architecture/system-map.md`](architecture/system-map.md)                         | `api/api_app.py`, target domain directories                                                         |
| API routes, services, repositories, DI, migrations, or API tests    | [`architecture/api.md`](architecture/api.md)                                       | `api/`, `api/tests/`                                                                                |
| App Router pages, providers, queries, mutations, or Playwright      | [`architecture/ui.md`](architecture/ui.md)                                         | `ui/src/`, `ui/tests/`                                                                              |
| Agent lifecycle, chat platform, model, or runtime selection         | [`features/agents.md`](features/agents.md)                                         | `api/domains/agents/`, `ui/src/features/agents/`                                                    |
| Runtime builders, Kubernetes agent resources, or service deployment | [`architecture/runtime-and-deployment.md`](architecture/runtime-and-deployment.md) | `api/domains/agents/builders/`, `helm/`, `.github/workflows/`                                       |
| Templates, template versions, required skills, or skill archives    | [`features/templates-and-skills.md`](features/templates-and-skills.md)             | `api/domains/templates/`, `api/domains/skills/`                                                     |
| Login, tokens, users, organizations, membership, or tenancy         | [`features/identity-and-organizations.md`](features/identity-and-organizations.md) | `api/domains/auth/`, `api/domains/users/`, `api/domains/organizations/`                             |
| Conversation history, tool-call audit, parsers, or telemetry ingest | [`features/activity-and-ingest.md`](features/activity-and-ingest.md)               | `api/ingest_app.py`, `api/domains/conversations/`, `api/domains/tool_calls/`, `api/domains/ingest/` |
| Spend summaries or per-agent cost attribution                       | [`features/costs.md`](features/costs.md)                                           | `api/domains/costs/`, `ui/src/features/costs/`                                                      |
| External provider credentials, Slack setup, or Google OAuth         | [`features/integrations.md`](features/integrations.md)                             | `api/domains/integrations/`, agent secret code                                                      |
| Architectural rationale or revisiting an accepted decision          | [`adr/README.md`](adr/README.md)                                                   | Related feature or architecture document                                                            |
| Domain terminology                                                  | [`../CONTEXT.md`](../CONTEXT.md)                                                   | Relevant feature document                                                                           |

## Maintenance

Update this map in the same change when a routed document, API domain, UI feature, runtime, or major responsibility is added, removed, renamed, or moved. Update the relevant feature or architecture document when its invariants, boundaries, state model, or change-impact surface changes.
