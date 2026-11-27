# One LiteLLM route per provider model, with explicit prices

Status: Accepted
Date: 2026-11-23
Origin: AF-447 slice 3 planning with the maintainers, 2026-11-17 and 2026-11-18; [LLM providers change log](../features/llm-providers/CHANGELOG.md)

Each model a Platform Administrator saves on an [LLM Provider Connection](../features/llm-providers.md) other than OpenRouter becomes its own LiteLLM route, `<slug>/<model_id>`, carrying the connection's key and all four of the model's per-token prices, with the input and output prices above 0. A model that isn't saved gets no route. The maintainers chose this because, at LiteLLM v1.108.6, a call LiteLLM can't price escapes spend tracking and budgets:

- A model with no price of its own and none in LiteLLM's price list is recorded at $0, with no error (`litellm/litellm_core_utils/litellm_logging.py:2036-2050,7046`).
- A call to a model priced at 0 skips every budget check (`litellm/proxy/auth/auth_checks.py:1342`).
- Agent keys carry no model restriction (`generate_key` in `api/infrastructure/litellm/client.py`), so an Agent can reach any route; only a route with a price keeps its calls inside the Agent's and the Organization's budgets.

A route's own prices are used for spend and budgets ahead of LiteLLM's price list (`litellm/cost_calculator.py:1007-1015`), so the stored prices decide what a call costs, and a LiteLLM upgrade can't change them.

## Consequences

- The API refuses an input or output price of 0 or less, and the database refuses it too. A cache price that LiteLLM's price list doesn't give is stored as the input price, so every route sends all four prices.
- Every saved model is a route write. A connection holds at most 50 models, which bounds how long its lock is held.
- LiteLLM also routes a request by a route's `litellm_params.model`, such as `anthropic/claude-sonnet-4-5`, not only by its `model_name` (`litellm/router.py:13641-13645`). Slice 6 checks whether key model lists close this.

## Accepted risk: DNS rebinding

When a key is saved, the API checks that an Azure or Custom base URL's host resolves to a public address and pins its own requests to it. LiteLLM connects to that host itself, so a host that later resolves to a private address would be reached from the LiteLLM pod. A NetworkPolicy limiting LiteLLM's egress was planned and dropped on 2026-11-18: staging's tenant release `tenant-agent-farm-staging` installs `allow-all-egress` (`podSelector: {}`, `egress: [{}]`), and NetworkPolicies only add permissions, so a policy for LiteLLM could restrict nothing there. Public was not checked. The risk is accepted because only Platform Administrators can set a base URL.
