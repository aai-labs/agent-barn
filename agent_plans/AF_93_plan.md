# AF-93 — Agents CRUD API: Implementation Plan

## Overview

Implement a full lifecycle API for AI agents. Each agent runs as a set of Kubernetes resources
in the `agent-farm` namespace. The API manages both the database state and the k8s resources.

---

## Requirements

| # | Requirement |
|---|---|
| R1 | `POST /v1/agents` creates an agent DB record (status=STOPPED). No k8s resources created. |
| R2 | `POST /v1/agents/{id}/start` provisions all 5 k8s resources and sets status=RUNNING. |
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

---

## Architecture Decisions

### Two-table design
- `agent_template` — versioned snapshot of 8 `.md` files. New row created on every PATCH that touches `.md` fields. Old versions retained for history.
- `agent` — live state record. Holds status, encrypted tokens, FK to current template.

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
- `AgentTemplate` SQLModel table: organization_id, version, 8 md fields
- `Agent` SQLModel table: organization_id, name, encrypted tokens, status, deleted_at, template FK
- `AgentCreate`: soul_md + identity_md required (min_length=1), others optional
- `AgentUpdate`: all fields optional
- `AgentRead`: no token fields
- `AgentFilter` + `get_agent_filter` FastAPI dependency

### `api/domains/agents/builders.py`
Five pure functions returning k8s manifests:
| Function | Resource | Notes |
|---|---|---|
| `build_config_map` | V1ConfigMap | data keys: SOUL.md … HEARTBEAT.md |
| `build_secret` | V1Secret | string_data: SLACK_BOT_TOKEN, SLACK_APP_TOKEN |
| `build_pvc` | V1PersistentVolumeClaim | ReadWriteOnce, 1Gi |
| `build_service` | V1Service | ClusterIP, port 80 → targetPort 8080 |
| `build_deployment` | V1Deployment | 1 replica; envFrom Secret; ConfigMap→/app/config, PVC→/app/data |

### `api/domains/agents/repository.py`
- `get_active(agent_id, org_id)` — returns None if soft-deleted
- `find_all_active(org_id, agent_filter, pagination)` — uses `func.count()` for total, optional status filter
- `get_template(template_id)` / `save_template(template)` / `save(agent)`

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
Seven thin handlers. All use `Depends(get_current_user())`.

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
21 integration tests covering all endpoints and error cases.

---

## Files Modified

### `api/core/config.py`
Added:
```python
agent_image: str = ""
agent_token_encryption_key: str = ""
```

### `api/pyproject.toml`
Added `"cryptography>=44.0.0"` to dependencies.

### `api/api_app.py`
Registered `agents_router` on the sub-api.

### `.env.spec`
Added `AGENT_IMAGE` and `AGENT_TOKEN_ENCRYPTION_KEY` entries with comments.

### `api/tests/steps/database.py`
Added `delegate.delete_all(Agent)` and `delegate.delete_all(AgentTemplate)` to `database_is_clean()`.
Agent must be deleted before AgentTemplate due to the RESTRICT FK.

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

- [ ] Add `AGENT_TOKEN_ENCRYPTION_KEY` to the `agentfarm-api` k8s Secret
- [ ] Add `AGENT_IMAGE` to the `agentfarm-api` k8s Secret
- [ ] Run migration: `kubectl exec -n agent-farm deploy/agentfarm-api -- python -m alembic upgrade head`
- [ ] Verify existing ServiceAccount Role covers: ConfigMaps, Secrets, Services, PVCs, Deployments (create/get/delete)
- [ ] Smoke test: create agent → start → `kubectl get pods -n agent-farm` → stop → delete
