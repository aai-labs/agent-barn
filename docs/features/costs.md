# Costs

## Read when

Read before changing spend attribution, LiteLLM integration, cost summaries, deleted-agent handling, cost status labels, or the Costs UI.

## Role in the system

Costs provides organization and per-agent spend views by querying LiteLLM and joining its key-based records to Agent Farm agents. Cost records are not persisted by the Costs domain.

## Invariants

- Organization summaries consider active and soft-deleted agents so historical spend remains attributable, but omit agents that have no LiteLLM key.
- The service obtains a LiteLLM spend report and joins records to agents through the identity derived from each decrypted per-agent LiteLLM key.
- Summary output aggregates total spend, model spend, daily spend, and per-agent spend.
- Per-Agent detail requires `cost.read` through the effective Agent Access Role. Agent Viewer, Editor, and Owner can read accessible active-Agent costs; Organization Owner/Admin and superuser in explicit Organization context may also read deleted-Agent history.
- Per-agent detail for an agent without a LiteLLM key returns zero-valued data with status `stopped`; the summary omits that agent.
- For agents with a key, cost-facing status is mapped to `active`, `stopped`, `error`, or `deleted`; it is not the persisted AgentStatus enum.
- Organization cost summaries require the Organization Permission `cost.read`; fixed Organization Owner/Admin roles and explicit superuser Organization context receive it. An Agent Access Role never authorizes an Organization-wide summary, and per-Agent detail cannot reveal inaccessible or deleted Agents.

## Boundaries

Agents own LiteLLM key creation, encryption, deletion blocking, and lifecycle status. The LiteLLM infrastructure client owns remote API behavior. Costs owns reporting-time joins and aggregation. Conversation and Tool Call data do not feed cost calculation.

## Source map

| Concern                       | Authoritative source                  |
| ----------------------------- | ------------------------------------- |
| Cost response contracts       | `../../api/domains/costs/models.py`         |
| Attribution and aggregation   | `../../api/domains/costs/service.py`        |
| HTTP routes                   | `../../api/domains/costs/routes.py`         |
| LiteLLM client                | `../../api/infrastructure/litellm/`         |
| Agent key lifecycle           | `../../api/domains/agents/service.py`       |
| UI schemas, hooks, and charts | `../../ui/src/features/costs/`              |
| Tests                         | `../../api/tests/integration/test_costs.py`, `../../api/tests/integration/test_agent_rbac.py` |

## Change impact

Attribution changes affect agent key lifecycle, LiteLLM response assumptions, deleted-agent behavior, API response schemas, UI charts, and cost integration tests. Status changes require checking both persisted AgentStatus and the cost-facing mapped labels.
