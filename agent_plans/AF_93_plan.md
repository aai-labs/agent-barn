# AF-93 — Agents CRUD API: Implementation Plan

## Overview

Implement a full lifecycle API for AI agents. Each agent runs as a set of Kubernetes resources
in the `agent-farm` namespace. The API manages both the database state and the k8s resources.

---

## Requirements

| # | Requirement |
|---|---|
| R1 | `POST /v1/agents` creates an agent DB record (status=STOPPED). No k8s resources created. |
| R2 | `POST /v1/agents/{id}/start` provisions all 5 k8s resources and sets status=RUNNING. Auto-configures openclaw (model + LiteLLM provider) via config overlay — no manual kubectl exec needed. |
| R3 | `POST /v1/agents/{id}/stop` deletes only the Deployment. Sets status=STOPPED. Service/PVC/ConfigMap/Secret persist. |
| R4 | `GET /v1/agents` returns paginated active agents for the org. Supports `?status=` filter. |
| R5 | `GET /v1/agents/{id}` returns a single active agent. |
| R6 | `PATCH /v1/agents/{id}` supports partial updates. Rejected (409) if RUNNING. If any `.md` field changes, a new `AgentTemplate` version is created. |
| R7 | `DELETE /v1/agents/{id}` tears down all k8s resources and soft-deletes the DB row. Returns 204. |
| R8 | Deleted agents never appear in list or get responses. |
| R9 | All endpoints return 401 without a valid session token. |
| R10 | All endpoints are scoped to the org resolved from the current session. |
| R11 | Slack tokens encrypted at rest (Fernet). Never returned in API responses. |
| R12 | K8s operations are idempotent. |
| R13 | `POST /v1/agents/{id}/pair` approves Slack pairing via API (no kubectl exec needed). |
| R14 | `GET /v1/agents/{id}/template/{version}` returns a specific historical template version. |
| R15 | Per-agent LiteLLM virtual key generated on create, injected on start, revoked on delete. |
| R16 | Per-agent `model` field. Falls back to `Config.agent_default_model` when empty. |

---

## Architecture Decisions

### Two-table design
- `agent_template` — versioned snapshot of 8 `.md` files. New row created on every PATCH that touches `.md` fields. Old versions retained for history. Has `agent_id` FK back to the agent for historical version lookup.
- `agent` — live state record. Holds status, encrypted tokens, per-agent model, FK to current template.

### Auto-configuration (no manual kubectl)
On `start_agent`, the API builds an openclaw config overlay in Python (`build_openclaw_config_overlay`) containing the LiteLLM provider URL and agent model. This JSON is included in the ConfigMap alongside a tiny init script (`init-openclaw.js`) that deep-merges the overlay into the PVC config at pod startup. The container command runs the init script before starting the gateway: `sh -c "node /app/config/init-openclaw.js && exec openclaw gateway --allow-unconfigured"`.

### Pairing via API
`POST /v1/agents/{id}/pair` runs `kubectl exec` (via subprocess) inside the agent pod to approve Slack pairing. Uses subprocess instead of the Python k8s client's websocket exec because the `agent-farm-user` SA has `create` but not `get` on `pods/exec`, and WebSocket always initiates with HTTP GET.

### Per-agent LiteLLM keys
Each agent gets its own LiteLLM virtual key generated via `/key/generate`. The key is encrypted and stored in the DB. On start, it's decrypted and injected into the pod's k8s Secret as `LITELLM_API_KEY`. On delete, the key is revoked (best-effort).

### Agent lifecycle state machine
```
STOPPED ──start──▶ RUNNING
RUNNING ──stop───▶ STOPPED
any     ──delete──▶ soft-deleted (deleted_at set)
ERROR             ← set if k8s call fails during start
```

### K8s resource naming
All 5 resources share the name `agent-{agent.id}` (UUID, DNS-safe).
Label set: `{"app": "agent-{agent.id}", "org-id": "{organization_id}"}`.

### Encryption
Fernet symmetric encryption (from `cryptography` package). Key stored in `Config.agent_token_encryption_key`. Encrypt on write, decrypt only inside `start_agent` to inject into the k8s Secret.

### Domain layout
Follows the existing canonical pattern:
```
api/domains/agents/
  __init__.py
  models.py       — DB models, enums, request/response schemas
  repository.py   — persistence layer
  service.py      — business logic + k8s orchestration
  routes.py       — thin FastAPI handlers
  builders.py     — pure functions that construct k8s manifest objects
  defaults.py     — default content for optional .md files

api/infrastructure/crypto.py   — Fernet encrypt/decrypt helpers
```

---

## Files Created

### `api/infrastructure/crypto.py`
Two pure functions: `encrypt_token(plaintext, key)` and `decrypt_token(ciphertext, key)`.
Used by the service to encrypt tokens on write and decrypt them on start.

### `api/domains/agents/defaults.py`
Default strings for the 6 optional `.md` files (USER, TOOLS, AGENTS, BOOT, BOOTSTRAP, HEARTBEAT).

### `api/domains/agents/models.py`
- `AgentStatus` enum: STOPPED, RUNNING, ERROR
- `AgentTemplate` SQLModel table: organization_id, agent_id (nullable FK back to agent), version, 8 md fields. Index on (agent_id, version) for historical lookups.
- `Agent` SQLModel table: organization_id, name, encrypted tokens (slack + litellm), status, deleted_at, template FK, model
- `AgentCreate`: soul_md + identity_md required (min_length=1), others optional, model optional
- `AgentUpdate`: all fields optional, including model
- `AgentRead`: no token fields, includes model
- `AgentTemplateRead`: all md fields + id, version, organization_id, timestamps
- `PairRequest`: platform + code (both required)
- `AgentFilter` + `get_agent_filter` FastAPI dependency

### `api/domains/agents/builders.py`
Five manifest builders + two auto-config helpers:
| Function | Resource | Notes |
|---|---|---|
| `build_config_map` | V1ConfigMap | data keys: SOUL.md … HEARTBEAT.md + `openclaw-config-overlay.json` + `init-openclaw.js` |
| `build_secret` | V1Secret | string_data: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, LITELLM_API_KEY |
| `build_pvc` | V1PersistentVolumeClaim | ReadWriteOnce, 1Gi |
| `build_service` | V1Service | ClusterIP, port 80 → targetPort 8080 |
| `build_deployment` | V1Deployment | 1 replica; envFrom Secret; ConfigMap→/app/config, PVC→/app/data; runs init script before gateway |
| `build_openclaw_config_overlay` | dict | Builds overlay JSON with LiteLLM provider URL + model config |
| `INIT_OPENCLAW_JS` | string constant | Tiny JS script that deep-merges overlay into PVC config at pod startup |

### `api/domains/agents/repository.py`
- `get_active(agent_id, org_id)` — returns None if soft-deleted
- `find_all_active(org_id, agent_filter, pagination)` — uses `func.count()` for total, optional status filter
- `get_template(template_id)` / `save_template(template)` / `save(agent)`
- `get_template_by_agent_and_version(agent_id, version, org_id)` — queries by agent_id + version for historical lookup

### `api/domains/agents/service.py`
Business logic layer. Key decisions:

**`start_agent`** — deletes ConfigMap and Secret before recreating them. Reason: `stop_agent`
only deletes the Deployment, leaving ConfigMap/Secret live. Without the pre-delete, a restart
after a PATCH would pick up stale content via `_create_or_get`'s 409 handler.
PVC and Service use `_create_or_get` (PVC preserves persistent data; Service spec never changes).

**`delete_agent`** — calls all 5 deletes unconditionally. Reason: an agent in ERROR status may
have a Deployment running even though status is not RUNNING. `_delete_ignoring_not_found` handles
the case where a resource doesn't exist (404 silently ignored).

### `api/domains/agents/routes.py`
Nine thin handlers. All use `Depends(get_current_user())`:
- `POST /agents` — create agent
- `GET /agents` — list agents (paginated, filterable)
- `GET /agents/{id}` — get single agent
- `GET /agents/{id}/template/{version}` — get historical template version
- `PATCH /agents/{id}` — partial update
- `DELETE /agents/{id}` — soft delete + k8s teardown
- `POST /agents/{id}/start` — provision k8s resources
- `POST /agents/{id}/stop` — delete deployment only
- `POST /agents/{id}/pair` — approve Slack pairing

### `api/migrations/versions/b4e7f91c2d38_add_agent_tables.py`
- `down_revision = "8f3c2a7d9b10"`
- Creates `agentstatus` enum, `agent_template` table, `agent` table
- Indexes: `ix_agent_organization_deleted` (compound on org + deleted_at), `ix_agent_status`
- Downgrade drops in reverse order

### `api/tests/steps/agent.py`
- `TEST_ENCRYPTION_KEY` — generated Fernet key for tests
- `MockK8sModule` — injector module that replaces `KubernetesClient` with a `MagicMock`
- `there_is_an_agent(name, status, deleted, organization_id)` — creates template + agent rows directly via repository
- `use_org_for_auth()` — scoped step that sets `_default_org_id` for the test's org and resets it to None on teardown (via `LambdaWith`)

### `api/tests/integration/test_agents.py`
45 integration tests covering all endpoints and error cases, including:
- CRUD operations (create, get, list, patch, delete)
- Lifecycle (start, stop)
- LiteLLM key generation/revocation
- Per-agent model + config overlay
- Pairing endpoint (success, stopped agent, no pod, no auth)
- Template fetch (success, missing version, deleted agent, no auth)

---

## Files Modified

### `api/core/config.py`
Added:
```python
agent_image: str = ""
agent_token_encryption_key: str = ""
agent_default_model: str = "litellm/gpt-5-mini"
agent_image_pull_secret: str = ""
agent_litellm_base_url: str = ""
```

### `api/pyproject.toml`
Added `"cryptography>=44.0.0"` to dependencies.

### `api/api_app.py`
Registered `agents_router` on the sub-api.

### `api/infrastructure/kubernetes/client.py`
Added `get_pod_name_for_deployment(deployment_name, namespace)` — finds the first Running pod for a deployment by label selector.
Added `exec_command(pod_name, namespace, command)` — runs `kubectl exec` via subprocess (uses SPDY/POST, compatible with SA that has `create` on `pods/exec`).

### `api/infrastructure/litellm/client.py` (new)
`LiteLLMClient` — reads LiteLLM master key from k8s secret, generates per-agent virtual keys via `/key/generate`, revokes via `/key/delete`.

### `api/Dockerfile`
Added kubectl binary installation (required for pairing endpoint's `exec_command`).

### `.env.spec`
Added entries: `AGENT_IMAGE`, `AGENT_TOKEN_ENCRYPTION_KEY`, `AGENT_DEFAULT_MODEL`, `AGENT_IMAGE_PULL_SECRET`, `LITELLM_SECRET_NAME`.

### `api/tests/steps/database.py`
Agent and AgentTemplate cleanup uses `TRUNCATE agent_template, agent CASCADE` to handle the circular FK (agent.template_id → agent_template, agent_template.agent_id → agent).

### Migrations
| File | Description |
|---|---|
| `b4e7f91c2d38_add_agent_tables.py` | Creates agentstatus enum, agent_template table, agent table |
| `c5f2a1e8d047_add_litellm_key_to_agent.py` | Adds litellm_key_encrypted column |
| `d8a3f12b4c59_add_model_to_agent.py` | Adds model column |
| `e9b4f23c5a71_add_agent_id_to_agent_template.py` | Adds agent_id FK + index to agent_template, backfills from agent.template_id |

---

## Bug Fixes Applied During Review

### Fix 1 — Stale ConfigMap/Secret after stop/start cycle
**Problem:** `stop_agent` deletes only the Deployment. On the next `start_agent`, `create_config_map`
and `create_secret` hit the `_create_or_get` 409 path and return the old resources. If the agent
was PATCHed between stop and start, the pod starts with outdated config and tokens.

**Fix:** In `start_agent`, call `delete_config_map` and `delete_secret` before the create calls.
`_delete_ignoring_not_found` silently handles the first-ever start where no resources exist yet.

### Fix 2 — Deployment leak on ERROR status
**Problem:** `delete_agent` originally guarded `delete_deployment` with `if status == RUNNING`.
An agent in ERROR state (start failed after Deployment was created) would leak the Deployment.

**Fix:** Remove the guard. Call `delete_deployment` unconditionally. `_delete_ignoring_not_found`
handles the case where no Deployment exists (STOPPED agent).

---

## Test Infrastructure Note

### How agent integration tests run

The agent integration tests in `test_agents.py` run entirely locally with no real Kubernetes
cluster required. `KubernetesClient` is replaced by a `MagicMock` via `MockK8sModule`, an
injector module override registered in `_GIVEN`. This means:

- All k8s calls (`create_deployment`, `delete_secret`, etc.) are recorded on the mock but never
  reach a cluster.
- Tests assert that the correct methods were called with the correct arguments.
- The real database (PostgreSQL via testcontainers) is used for all DB assertions.
- `make test-api-k8s` runs `test_kubernetes_client.py` separately against a real cluster to
  verify the `KubernetesClient` wrapper itself works. The correctness of the manifests built by
  `builders.py` against a live cluster requires a manual smoke test (see Deployment Checklist).

### Auth global state

`_default_org_id` is a module-level global in `api/domains/auth/utils.py` set during app lifespan
from the default organization. In tests, lifespan does not run (TestClient not used as context
manager), so it stays None, causing `require_current_user_organization()` to raise 403.

Solution: `use_org_for_auth()` step sets `_default_org_id` for the duration of each agent test
and resets it to None on teardown, preventing state from leaking into other test files.

---

## Deployment Checklist

- [ ] Add `AGENT_TOKEN_ENCRYPTION_KEY` to the `agentfarm-api` k8s Secret (Fernet key, generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- [ ] Add `AGENT_IMAGE` to the `agentfarm-api` k8s Secret
- [ ] Add `AGENT_IMAGE_PULL_SECRET=registry-pull-secret` to the `agentfarm-api` k8s Secret
- [ ] Ensure `LITELLM_BASE_URL` and `LITELLM_SECRET_NAME` are set in the `agentfarm-api` k8s Secret
- [ ] Ensure kubectl binary is available in the API container (added via Dockerfile)
- [ ] Ensure the `agent-farm-user` kubeconfig secret is mounted and `K8S_KUBECONFIG_PATH` points to it
- [ ] Run migration: `kubectl exec -n agent-farm deploy/agentfarm-api -- python -m alembic upgrade head`
- [ ] Verify existing ServiceAccount Role covers: ConfigMaps, Secrets, Services, PVCs, Deployments (create/get/delete), Pods (list), Pods/exec (create)
- [ ] Smoke test: create agent → start → `kubectl get pods -n agent-farm` → pair via API → stop → delete

---

## Local Dev: How to Launch and Test a Bot

### Prerequisites

- Port-forward to LiteLLM: `kubectl port-forward -n agent-farm deploy/litellm 4000:4000` (keep open in a separate terminal)
- API running locally with these `.env` values set:
  - `LITELLM_BASE_URL=http://localhost:4000` (API uses this for key generation via port-forward)
  - `AGENT_LITELLM_BASE_URL=http://litellm:4000` (injected into pods as LITELLM_BASE_URL)
  - `LITELLM_SECRET_NAME=litellm`
  - `AGENT_TOKEN_ENCRYPTION_KEY=<your-fernet-key>`
  - `AGENT_IMAGE=<registry-url>/agentfarm-openclaw-base:<version>`

### Step 1 — Create the agent

`POST /api/v1/agents` with body:
```json
{
  "name": "My Agent",
  "slack_bot_token": "xoxb-...",
  "slack_app_token": "xapp-...",
  "soul_md": "# Soul\n\nYour agent soul.",
  "identity_md": "# Identity\n\nYour agent identity.",
  "model": "litellm/gpt-5-mini"
}
```
Note the `id` from the 201 response. The `model` field is optional — if omitted, the agent uses
the global default from `AGENT_DEFAULT_MODEL` (currently `litellm/gpt-5-mini`).

### Step 2 — Start the agent

`POST /api/v1/agents/{id}/start` — expect 200 with `status: "RUNNING"`.

This automatically:
- Generates and injects per-agent LiteLLM key into the pod Secret
- Builds the openclaw config overlay (LiteLLM provider URL + model) and includes it in the ConfigMap
- Runs the init script (`init-openclaw.js`) on pod startup to merge the overlay into openclaw config
- No manual `kubectl exec` needed for LiteLLM config or model setup

### Step 3 — Wait for pod to be ready

```
kubectl get pods -n agent-farm -w
```
Wait until the agent pod shows `1/1 Running`. Check pod logs for `[init-openclaw] Config merged successfully`.

### Step 4 — Approve Slack pairing

Send a DM to the bot in Slack. It will reply with a pairing code. Approve it via the API:

```
POST /api/v1/agents/{id}/pair
{
  "platform": "slack",
  "code": "<pairing-code>"
}
```

Expect 200 with `{"message": "Pairing approved"}` (or similar output from openclaw).

### Step 5 — Test

Send another message in the DM. The bot should respond. Monitor with:

```
kubectl logs -n agent-farm deploy/agent-{id} -f
```

### Fetching template history

To retrieve a specific historical version of an agent's template:

```
GET /api/v1/agents/{id}/template/{version}
```

Returns the full template content (all 8 `.md` fields) for that version. Version 1 is the original
template from agent creation. Each PATCH that changes `.md` fields creates a new version.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Incorrect API key` | Request going to OpenAI instead of LiteLLM | Check agent `model` field is `litellm/gpt-5-mini`, check pod logs for init script output |
| `[init-openclaw] No overlay found` | ConfigMap missing overlay | Stop and re-start the agent to recreate ConfigMap |
| No response, no logs after message | Bot not in channel or pairing not approved | `/invite @botname` in channel; check DM for pairing prompt |
| `Something went wrong` in Slack | Check pod logs for specific error | `kubectl logs deploy/agent-{id} -n agent-farm --tail=20` |
| LiteLLM crash-looping | LiteLLM's own Postgres (`postgres-litellm`) is down | Check `kubectl get pods -n agent-farm \| grep postgres` |
| Pod `ImagePullBackOff` | Registry credentials issue | Verify `AGENT_IMAGE_PULL_SECRET` is set and the secret exists in namespace |
| Pairing endpoint returns 409 | Agent not running or no running pod found | Verify agent status is RUNNING and pod is `1/1 Running` |
| Pairing endpoint returns 500 | kubectl exec failed inside API container | Check API logs; verify kubectl binary is installed in API container and kubeconfig is mounted |

### Notes

- The PVC is mounted at `/home/node/.openclaw` — all openclaw config (pairing approvals, model settings, provider config) persists across pod restarts.
- Steps 4-6 are only needed once per agent. After initial setup, stop/start preserves the config.
- The model name (`gpt-5-mini`) must match what's configured in LiteLLM's `model_list`. Check available models: `curl -H "Authorization: Bearer <master-key>" http://localhost:4000/models`
