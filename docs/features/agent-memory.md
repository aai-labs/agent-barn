# Agent Memory

## Read when

Read before changing whether an Agent may use long-term memory, who may turn it on, Memory Grants, or the rules that decide which memories an Agent recalls.

## Role in the system

Agent Memory gives an Agent long-term memory backed by a self-hosted Hindsight instance. It is opt-in per Agent and adds to each Runtime's own memory (Hermes `MEMORY.md`/`USER.md`, OpenClaw `memory-core`); it never replaces it.

Delivery is staged; see [`agent-memory/CHANGELOG.md`](agent-memory/CHANGELOG.md). The opt-in, Memory Grants, gateway, per-start credentials, runtime plugins, and the memory UI are implemented. Opted-in Agents automatically recall and retain through Hindsight when the optional backend and gateway are deployed.

## Memory data contract

- An Agent's memories are private to it by default. Each Organization's memories live in one Hindsight bank, `org-<organization_id>`; inside it, every memory an Agent writes is tagged `agent:<agent_id>`.
- Turning memory off stops the Agent recalling and retaining. Its stored memories are kept, and Agents granted access to them can still recall them, until the Agent is deleted.
- Deletion immediately removes the Agent's gateway access and its Memory Grants in both directions. Hindsight purging is asynchronous through a durable deletion tombstone; see [Deletion cleanup](#deletion-cleanup).
- Memories live outside the Agent's volume; an Agent Restore Point does not capture or roll them back.
- Memories are shared across all users of one Agent on purpose: a fact one person tells an Agent can be recalled in another person's session with that Agent.

## Implemented invariants

- `agent.memory_enabled` defaults to false. Changing it requires the Agent Permission `agent.memory.manage`, which the locked Agent Owner role holds. In practice that means the Agent Creator (who receives Agent Owner on creation), Organization Owners and Admins (implicit Agent Owner), and anyone later given Agent Owner access. Agent Editors and Viewers cannot.
- Memory Grants require the Organization Permission `memory.access.manage`, which only Organization Owners and Admins hold. Agent Owner authority over either Agent is not enough.
- A Memory Grant is directional: it gives its receiving Agent (`agent_id`) the selected access, and gives nothing back to a source Agent.
  - With `source_agent_id` NULL it grants **Organization Memory** with explicit `access`: `read` permits recalling `scope:team`; `read_write` permits both recall and explicit shared saves. An Agent can always recall what it itself wrote.
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
- `POST /organizations/{organization_id}/memory-grants` with `{"agent_id", "source_agent_id", "access"}` creates one; `access` defaults to `read`. `read_write` is allowed only for Organization Memory; writing to another Agent's memories returns 400. Omit or null `source_agent_id` for Organization Memory. A missing, deleted or other-Organization Agent is 404, a self-grant is 400, a duplicate is 409.
- `DELETE /organizations/{organization_id}/memory-grants/{grant_id}` revokes one (204).

### View an Agent's saved memories

`GET /organizations/{organization_id}/agents/{agent_id}/memory/items?search=&page=&page_size=` returns a read-only page of the memories that Agent itself wrote: `id`, `type` (`world`, `experience`, or `observation`), `text`, `mentioned_at`, and `shared` (true when it carries `scope:team`). Entities, context, chunks, document and source IDs, metadata, and history are never returned. `page_size` is at most 50 and `page` at most 2,000; `search` is at most 200 characters.

- Content authorization reuses the Agent Permission `activity.read` through the normal Agent visibility checks: hidden, other-Organization, and deleted Agents are 404, and a visible Agent without `activity.read` is 403. `agent.memory.manage` and `memory.access.manage` govern settings and grants, not reading saved content.
- Only the selected Agent's own tag is listed. Memories it can recall from Memory Grants or Organization Memory written by other Agents are not shown. Stored memories are viewable while the Agent is stopped or memory is disabled, until it is deleted.
- `mentioned_at` is the time Hindsight recorded for the memory, not necessarily when it was persisted; Hindsight 0.10.2 does not expose a creation time on this endpoint. Results are ordered most recently mentioned first. Memories without a mention time have none.
- The product API holds no Hindsight credential. After authorizing the person it sends the gateway's separate viewer (`/memory/view/v1/memories`, never the Agent allowlist) a 30-second JWT naming one Organization and Agent, with an audience and operation distinct from user access tokens and Agent credentials. The gateway rechecks that the Agent is undeleted in an existing Organization, derives the `org-<organization_id>` bank, forces `tags=agent:<agent_id>&tags_match=any_strict`, and accepts only `search`, `limit`, and `offset`. Agent credentials are still refused on every list path.
- Hindsight 0.10.2 applies the tag filter before counting, so `total` covers only the Agent's rows. The gateway fails closed with a generic 502 if any returned row lacks that tag, has an unknown type, or the page is larger than requested or than its total. A bank that does not exist yet is an empty page. Search is a case-insensitive substring match on memory text and context with SQL wildcards escaped; it can match context that is not shown. Upstream errors are generic 502 or 503.

### Use the memory UI

- Agent configuration → **Memory** shows `memory_enabled` and, for people with `agent.memory.manage`, lets them change it. A running Agent with `agent.lifecycle.manage` uses **Save and Restart**: the UI stops it, saves the setting, and starts it again. If saving fails after stopping, the shared lifecycle flow still attempts to start it. Save or lifecycle failures remain visible inline. A stopped Agent uses **Save** and stays stopped. People without lifecycle permission can save without restarting; the UI explains that someone with lifecycle access must restart a running Agent to activate memory. The memory API itself does not restart the Agent; turning it off rejects memory requests immediately and keeps stored memories.
- Organization Settings → **Memory access** is visible only to the Organization's Owners and Admins, matching `memory.access.manage`; a platform administrator who is only a Member does not see it. It lists grants, creates one for an Agent to Organization Memory with an explicit **Read only** or **Read and write** selection, or to another Agent's private memories marked **Read only** (never itself), and revokes one after confirmation. To change a permission, revoke the current grant and create the desired one. A duplicate is stopped before submission and shown if the server still returns 409. The grant form uses full-width Agent, memory source, and short permission selectors; contextual help and the grant action sit below the fields. Fields stack on narrow screens.
- Agent page → **Memory** appears only with `activity.read` and queries only then. It is read-only; see [View an Agent's saved memories](#view-an-agents-saved-memories). Memory text is rendered as plain text.
- Grants and memory items are Organization-scoped query families; the `memory-grants` family is evicted on an Organization switch and keys carry the Organization API base.

### Explicit Organization Memory saves

Both runtimes expose `/tmp/agentbarn-bin/agentbarn-memory remember-organization` through their
terminal tool. Provide the fact on standard input, for example:

```sh
/tmp/agentbarn-bin/agentbarn-memory remember-organization <<'MEMORY'
The organization uses EUR for customer invoices.
MEMORY
```

The tool sends only content to `POST /memory/v1/organization-memory`, using its
existing per-start credential. It has no bank, Agent identity, or tag parameters.
The gateway checks the current write grant and spend policy, forces the writer's
identity, `scope:team`, `per_tag` observations, and a fresh team document namespace.
Missing write access returns 403; revocation applies on the next request. A 202
means extraction was accepted asynchronously, not that recall is already ready.
Failures are reported without backend content or credentials; the tool bypasses
environment proxies and refuses redirects. Automatic saves stay private.
The tool and instructions are mounted from API-owned runtime configuration;
existing Agents must restart to receive them. Memory must be enabled. Instructions
use the absolute installed path because terminal login shells can reset PATH;
the Hermes runtime contract executes those instructions through its real terminal tool.

Migration `c95f20b8413a` consolidates existing Organization grants into one
permission per Agent. Existing read grants stay read-only. Existing write grants,
including Agents with both grants, become `read_write`; this adds recall to any
previous write-only grant. When merging, the writer's ID and provenance are kept.
Source-Agent grants stay read-only. New grants default to read. Audit events use
`read` or `read_write`; historical `write` and absent access modes remain readable.
Downgrading this migration restores separate read and write rows for combined
grants, preserving their effective permissions. Rolling back further through
`b84e19a7302f` restores the original combined Organization Memory semantics.
Review grants before rolling back.

### Deletion cleanup

Agent deletion clears its memory credential, removes grants where it is either reader
or source, and inserts one `agent_memory_purge` tombstone in the same transaction
as the soft deletion and `agent.deleted` event. Grant cleanup is a consequence of
that deletion event; it emits no separate user-initiated grant-revocation events.
Migration `a63e8c941d20` queues previously deleted Agents and removes stale grants.
Tombstones have no foreign keys, so they survive subsequent Organization deletion.
Grant insertion rechecks and holds shared locks on its same-Organization, undeleted
targets through commit, so a grant racing deletion cannot be inserted afterward.

The operator-only worker derives the bank and Agent tag from the tombstone. It lists
documents with `any_strict` and deletes only IDs in that Agent's
`agent:<id>:private:` or `agent:<id>:team:` namespace carrying its exact tag.
It never deletes a bank or another Agent's documents. Hindsight 0.10.2 document
deletion removes its facts and invalidates dependent observations, requeuing surviving
sources. Unexpected document shapes/names/tags fail closed. Absent banks and already
deleted documents are safe to repeat. Live or tenant-mismatched Agents are refused.

Cleanup does not block deletion. Until it runs, shared facts tagged `scope:team` can
remain in Hindsight; private source grants are removed immediately. This removes
the deleted Agent's own documents, not copies other Agents may have retained.

Workers claim one row with a ten-minute lease and `SKIP LOCKED`. Failures use
exponential delays from 30 seconds to one hour, serviced on the job's schedule.
Expired leases are reclaimable; stale workers cannot overwrite newer claims. Runs
are bounded to 20 tasks, 100 documents per task, and four minutes, with ten-second
backend timeouts. Shrinking document pages are always fetched at offset zero.
Successful tombstones remain scheduled hourly: Hindsight work accepted before deletion
may finish later and recreate a document. `last_cleaned_at` records the last empty
scan, not a guarantee that earlier background work ended. Stored errors are generic
codes; logs contain only Agent, Organization, and result. No cleanup endpoint is
exposed to users, Agent tokens, or viewer capabilities. Scheduling/manual execution
belong in [operations](../guidelines/operations.md#agent-memory-deployment).

### Use the memory gateway

The separate `api.memory_main:app` process serves port 8003 under `/memory/v1`. The plugin API URL is that base; plugin requests append `/v1/default/banks/{bank_id}/...`. Every request under this base requires the per-start Agent bearer credential. The unprefixed `/health` is a process probe only.

| Method and path relative to the base | Behavior |
| --- | --- |
| `POST /organization-memory` | Explicit shared save; write grant required; content only; 202 accepted |
| `POST /v1/default/banks/{bank_id}/memories` | Retain with forced write tags and document scope |
| `POST /v1/default/banks/{bank_id}/memories/recall` | Recall with current readable tags and `any_strict` |
| `POST /v1/default/banks/{bank_id}/reflect` | Reflect with the same tag restrictions |
| `GET /health`, `GET /version` | Authenticated plugin compatibility checks |
| `GET /v1/default/banks/{bank_id}/operations/{operation_id}` | 404; operation details are not exposed |
| Everything else | 403 |

The token determines the Organization and Agent. Client bank names, query parameters, headers other than the bearer credential, tag filters, and unknown payload fields cannot override them. Recall and reflect receive the Agent's own tag, granted source tags, and `scope:team` only with an Organization Memory read grant. Untagged memories are excluded by `any_strict`.

Retain always forces `agent:<agent_id>` and `observation_scopes: per_tag`. It adds `scope:team` only when the Agent requests that tag and holds an Organization Memory write grant; otherwise a shared retain is rejected with 403. Document IDs are namespaced by Agent and private/Organization scope, with the client ID hashed. Separate scope namespaces prevent appending a shared turn from republishing earlier private turns. Operation IDs are namespaced by Agent too. Missing document IDs produce new namespaced IDs.

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
| Viewer fields, search, or listing contract | This document, `api/domains/agent_memory/view_service.py`, the pinned-image contract test, the UI memory tab |
| Grant semantics or tags | This document, `CONTEXT.md`, gateway policy and contract tests |
| Memory Grant schema | Alembic migration, `api/domains/agent_memory/models.py` |
| Gateway credentials or Agent lifecycle | Alembic migration, Agent start/persistence flow, gateway authentication tests |
| Plugin request shapes or Hindsight version | Sanitized captures, gateway DTOs and replay tests, runtime image contracts, backend chart |
| Gateway/backend deployment | [`operations.md`](../guidelines/operations.md#agent-memory-deployment), chart checks, runtime/deployment architecture |
| Memory spend policy or accounting freshness | [`costs.md`](costs.md#organization-llm-budgets), cost sync heartbeat, gateway spend tests, deployment job schedules |

## Code map

- `api/domains/agent_memory/`: opt-in, Memory Grants, their Domain Events, gateway authentication and payload policy; `view_*.py` hold the read-only viewer (capability, product-API client, gateway route and service).
- `api/infrastructure/hindsight/`: authenticated upstream HTTP client.
- `api/memory_app.py`, `api/memory_main.py`: gateway composition and process entry point.
- `api/domains/agents/service.py`: start-time memory credentials; Agent lifecycle persistence copies their hash.
- `helm/hindsight/`, `helm/agentbarn-api/templates/memory-deployment.yaml`: backend and gateway deployments; Helmfile owns optional release ordering.
- `ui/src/features/agent-memory/`: the setting, access panel, and Memory tab; composed from the Agent configuration page, the Agent detail page, and Organization Settings.
- `api/domains/rbac/catalog.py`: `agent.memory.manage`, `memory.access.manage`.
- `api/tests/integration/test_agent_memory.py`: permission, tenancy and audit contract.
- `api/tests/integration/test_memory_gateway.py`, `api/tests/fixtures/agent_memory/`: HTTP policy, credential lifecycle, and sanitized plugin request captures.
- `api/tests/integration/test_agent_memory_viewer.py`, `test_agent_memory_viewer_contract.py`: viewer permission, tenancy, capability, and failure behavior; the contract file runs the pinned Hindsight 0.10.2 image to prove tag-filtered items and totals, search, and pagination.
- `api/tests/integration/test_rbac_schema.py`: catalogue seeding, existing-Agent defaults, and migration rollback coverage.
