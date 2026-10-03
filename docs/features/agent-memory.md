# Agent Memory

## Read when

Read before changing whether an Agent may use long-term memory, who may turn it on, Memory Grants, or the rules that decide which memories an Agent recalls.

## Role in the system

Agent Memory gives an Agent long-term memory backed by a self-hosted Hindsight instance. It is opt-in per Agent and adds to each Runtime's own memory (Hermes `MEMORY.md`/`USER.md`, OpenClaw `memory-core`); it never replaces it.

Delivery is staged; see [`agent-memory/CHANGELOG.md`](agent-memory/CHANGELOG.md). The opt-in, Memory Grants, gateway, per-start credentials, and runtime plugins are implemented. Opted-in Agents automatically recall and retain through Hindsight when the optional backend and gateway are deployed.

## Memory data contract

- An Agent's memories are private to it by default. Each Organization's memories live in one Hindsight bank, `org-<organization_id>`; inside it, every memory an Agent writes is tagged `agent:<agent_id>`.
- Turning memory off stops the Agent recalling and retaining. Its stored memories are kept, and Agents granted access to them can still recall them, until the Agent is deleted.
- Deletion immediately removes the Agent's gateway access and its tag from other Agents' recall filters. Physical purging and grant cleanup are pending the lifecycle slice.
- Memories live outside the Agent's volume; an Agent Restore Point does not capture or roll them back.
- Memories are shared across all users of one Agent on purpose: a fact one person tells an Agent can be recalled in another person's session with that Agent.

## Implemented invariants

- `agent.memory_enabled` defaults to false. Changing it requires the Agent Permission `agent.memory.manage`, which the locked Agent Owner role holds. In practice that means the Agent Creator (who receives Agent Owner on creation), Organization Owners and Admins (implicit Agent Owner), and anyone later given Agent Owner access. Agent Editors and Viewers cannot.
- Memory Grants require the Organization Permission `memory.access.manage`, which only Organization Owners and Admins hold. Agent Owner authority over either Agent is not enough.
- A Memory Grant is directional: it lets its reading Agent (`agent_id`) recall memories, and gives nothing back to the source.
  - With `source_agent_id` NULL it grants **Organization Memory**: the Agent may recall memories tagged `scope:team` and may write them. An Agent without this grant can neither read nor write Organization Memory.
  - With `source_agent_id` set it lets the Agent recall that one source Agent's private memories.
- Both Agents in a grant belong to the same Organization (composite foreign keys), an Agent cannot be granted its own memories (`ck_agent_memory_grant_not_self`), and each reader holds at most one grant per source and one Organization Memory grant (partial unique indexes).
- Grants control recall and, for Organization Memory, permission to write. Creating or revoking one never moves or rewrites stored memories.
- Every start with memory enabled mints a fresh bearer credential. Only its SHA-256 hash is stored on the Agent; plaintext is injected as `MEMORY_API_KEY` in the runtime Secret alongside `MEMORY_URL`. It is never exposed by Agent reads. A start with memory disabled stores no hash or memory environment variables.
- The gateway authenticates against current persisted state: the Agent must exist in an existing Organization, be undeleted, running, and memory-enabled. Stopping, disabling, or deleting it denies its credential on the next request; starting again invalidates the previous credential. Enabling memory on an Agent started without it requires a restart to receive credentials.
- Grants are read on every request. A disabled or stopped source Agent remains readable while it is undeleted. Revoked grants and deleted sources immediately disappear from subsequent recall filters.
- Turning memory on or off and creating or revoking a grant each publish a Domain Event to the security-audit projection: `agent.memory.enabled`, `agent.memory.disabled`, `agent.memory_grant.created`, `agent.memory_grant.revoked`. The Event Subject is the reading Agent. Repeating the current memory setting publishes nothing.

## Primary flows

### Turn memory on or off

`PUT /organizations/{organization_id}/agents/{agent_id}/memory` with `{"enabled": bool}`. An Agent the caller cannot see is 404; a visible Agent without `agent.memory.manage` is 403. Agent reads report `memory_enabled`, and `allowed_actions` includes `agent.memory.manage` when the caller may change it.

### Manage Memory Grants

- `GET /organizations/{organization_id}/memory-grants` lists grants whose Agents are not deleted.
- `POST /organizations/{organization_id}/memory-grants` with `{"agent_id", "source_agent_id"}` creates one; omit or null `source_agent_id` for Organization Memory. A missing, deleted or other-Organization Agent is 404, a self-grant is 400, a duplicate is 409.
- `DELETE /organizations/{organization_id}/memory-grants/{grant_id}` revokes one (204).

### Use the memory gateway

The separate `api.memory_main:app` process serves port 8003 under `/memory/v1`. The plugin API URL is that base; plugin requests append `/v1/default/banks/{bank_id}/...`. Every request under this base requires the per-start Agent bearer credential. The unprefixed `/health` is a process probe only.

| Method and path relative to the base | Behavior |
| --- | --- |
| `POST /v1/default/banks/{bank_id}/memories` | Retain with forced write tags and document scope |
| `POST /v1/default/banks/{bank_id}/memories/recall` | Recall with current readable tags and `any_strict` |
| `POST /v1/default/banks/{bank_id}/reflect` | Reflect with the same tag restrictions |
| `GET /health`, `GET /version` | Authenticated plugin compatibility checks |
| `GET /v1/default/banks/{bank_id}/operations/{operation_id}` | 404; operation details are not exposed |
| Everything else | 403 |

The token determines the Organization and Agent. Client bank names, query parameters, headers other than the bearer credential, tag filters, and unknown payload fields cannot override them. Recall and reflect receive the Agent's own tag, granted source tags, and `scope:team` only with an Organization Memory grant. Untagged memories are excluded by `any_strict`.

Retain always forces `agent:<agent_id>` and `observation_scopes: per_tag`. It adds `scope:team` only when the Agent requests that tag and holds an Organization Memory grant. Document IDs are namespaced by Agent and private/Organization scope, with the client ID hashed. Separate scope namespaces prevent appending a shared turn from republishing earlier private turns. Operation IDs are namespaced by Agent too. Missing document IDs produce new namespaced IDs.

Recall traces, raw chunks, and source-fact expansion are disabled. Reflect excludes mental models, global directive application, and fact/tool-call traces. These response surfaces remain disabled until their tag isolation is verified. Requests use a bounded subset of the pinned Hindsight 0.10.2 contract: at most 2MiB per body, 20 retain items, and 100,000 content characters per item. Malformed supported requests return 422; oversized bodies return 413.

The gateway sends only its own Hindsight bearer credential upstream and does not follow redirects or environment proxies. Upstream errors become generic errors without backend content or headers. Request logs contain Agent, Organization, canonical bank/endpoint, effective access tags, and status; memory content, client paths, and credentials are excluded.

Organization suspension is not a current lifecycle state, so there is no suspension gate. Organization model costs are attributed through LiteLLM. Retain and reflect return 429 when combined observed runtime and memory spend reaches the Organization limit, or 503 when capped-Organization accounting data is unavailable or stale. Recall remains available. See [Costs](costs.md#organization-llm-budgets) for the authoritative spend-limit contract and its accounting delay. Deployment and credential rotation belong to [`operations.md`](../guidelines/operations.md#agent-memory-deployment).

## Runtime integration

At start, `memory_enabled` selects the Hindsight provider alongside native memory.
Hermes keeps its `MEMORY.md` and `USER.md` stores enabled. OpenClaw keeps its
`memory-core` slot; the image removes `kind: memory` from the pinned Hindsight
plugin manifest so its generic hooks can run alongside that slot.

- Hermes uses the bundled provider in `v2026.8.19` and image-installed
  `hindsight-client==0.6.1`. OpenClaw uses `@vectorize-io/hindsight-openclaw@0.13.0`
  and `@vectorize-io/hindsight-client@0.8.6` with core `2026.8.2`.
- Both use the gateway URL and the fresh Agent credential, a static compatibility
  bank name (`agentbarn`, replaced by the gateway), automatic recall, and retain
  after each completed turn. Recall requests world facts, experiences, and
  observations with a low budget and a 1,024-token limit.
- The retain context asks for durable facts, preferences, decisions, and working
  conventions, excluding transient progress and secrets. It guides extraction;
  the gateway independently enforces bank, tags, and document isolation.
- Runtime startup waits up to 15 seconds for authenticated gateway health so the
  newly minted credential can be persisted before provider initialization. It
  continues with native memory if the gateway remains unavailable.
- Startup replaces stale provider settings. Hermes writes its settings without
  the credential and reads `HINDSIGHT_API_KEY` from the environment. OpenClaw
  persists environment placeholders rather than the bearer credential and permits
  conversation access for this plugin's recall/retain hooks. Bank administration
  and OpenClaw knowledge tools are disabled.
- Disabling memory rejects gateway requests immediately. Restarting removes the
  provider configuration while preserving native memory and stored Hindsight data.
  Enabling requires a restart to activate the plugin and receive credentials.

Pinned-runtime contract tests exercise generated startup configuration, provider
loading, recall injection, completed-turn retain, stale configuration replacement,
and disabling on the same persistent volume. They use a deterministic HTTP backend
and do not measure Hindsight extraction quality.

## Change impact

| Change | Also update |
| --- | --- |
| Who may toggle memory or manage grants | [`rbac/IMPLEMENTATION-BRIEF.md`](rbac/IMPLEMENTATION-BRIEF.md), `api/domains/rbac/catalog.py`, a catalogue migration |
| Grant semantics or tags | This document, `CONTEXT.md`, gateway policy and contract tests |
| Memory Grant schema | Alembic migration, `api/domains/agent_memory/models.py` |
| Gateway credentials or Agent lifecycle | Alembic migration, Agent start/persistence flow, gateway authentication tests |
| Plugin request shapes or Hindsight version | Sanitized captures, gateway DTOs and replay tests, runtime image contracts, backend chart |
| Gateway/backend deployment | [`operations.md`](../guidelines/operations.md#agent-memory-deployment), chart checks, runtime/deployment architecture |
| Memory spend policy or accounting freshness | [`costs.md`](costs.md#organization-llm-budgets), cost sync heartbeat, gateway spend tests, deployment job schedules |

## Code map

- `api/domains/agent_memory/`: opt-in, Memory Grants, their Domain Events, gateway authentication and payload policy.
- `api/infrastructure/hindsight/`: authenticated upstream HTTP client.
- `api/memory_app.py`, `api/memory_main.py`: gateway composition and process entry point.
- `api/domains/agents/service.py`: start-time memory credentials; Agent lifecycle persistence copies their hash.
- `helm/hindsight/`, `helm/agentbarn-api/templates/memory-deployment.yaml`: backend and gateway deployments; Helmfile owns optional release ordering.
- `api/domains/rbac/catalog.py`: `agent.memory.manage`, `memory.access.manage`.
- `api/tests/integration/test_agent_memory.py`: permission, tenancy and audit contract.
- `api/tests/integration/test_memory_gateway.py`, `api/tests/fixtures/agent_memory/`: HTTP policy, credential lifecycle, and sanitized plugin request captures.
- `api/tests/integration/test_rbac_schema.py`: catalogue seeding, existing-Agent defaults, and migration rollback coverage.
