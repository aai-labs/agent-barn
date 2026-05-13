# AF-92 — Kubernetes Client Wrapper

## Context

The project needs to programmatically manage Kubernetes resources for agents. All cluster management was previously done via Helm/helmfile. This module gives the application the ability to create, delete, retrieve, and list the five resource types that make up a complete agent deployment — without touching Helm or kubectl.

---

## Decisions

| Concern | Decision |
|---|---|
| Auth | Auto-detect: try in-cluster first, fall back to kubeconfig path from config |
| Test cluster | Shared/persistent dev cluster (kubeconfig injected via env var) |
| Namespace strategy | Shared namespace (`agent-farm`), label-based per-agent filtering |
| Create input | Full `V1*` kubernetes-client objects |
| Idempotent create | No-op: catch 409, return existing resource unchanged |
| Idempotent delete | No-op: catch 404, return None without raising |
| `get` when not found | Return `None` |
| Module shape | Single `KubernetesClient` class |
| Config | New fields on existing `api/core/config.py` Pydantic Settings |
| Test cleanup | Unique `test-run-id=<uuid>` label on every test resource; autouse session fixture deletes all matching resources after the run |

---

## Files Changed

| File | Change |
|---|---|
| `api/pyproject.toml` | Added `kubernetes>=31.0.0` dependency |
| `api/core/config.py` | Added `k8s_kubeconfig_path` and `k8s_namespace` fields to `Config` |
| `api/infrastructure/kubernetes/__init__.py` | Created — re-exports `KubernetesClient` |
| `api/infrastructure/kubernetes/client.py` | Created — core implementation |
| `api/infrastructure/app.py` | Added `provide_kubernetes_client` singleton provider to `AppModule` |
| `api/tests/unit/test_kubernetes_client.py` | Created — 8 unit tests, no cluster required |
| `api/tests/integration/test_kubernetes_client.py` | Created — 11 integration tests against real cluster |
| `.env.spec` | Added `K8S_KUBECONFIG_PATH` and `K8S_NAMESPACE` |

---

## Implementation

### Connection (`__post_init__`)

```
if k8s_kubeconfig_path is set → load that file
else → try in-cluster auth → fall back to ~/.kube/config
```

Runs once at singleton construction. Both `AppsV1Api` (Deployments) and `CoreV1Api` (Service, PVC, Secret, ConfigMap) are initialised here and reused for all subsequent calls.

### Idempotency helpers

Three private helpers centralise all error-handling logic. No public method contains its own try/except.

- `_create_or_get` — catches `ApiException(409)`, reads and returns the existing resource
- `_delete_ignoring_not_found` — catches `ApiException(404)`, silences it
- `_get_or_none` — catches `ApiException(404)`, returns `None`

All other `ApiException` statuses (403, 422, 500, etc.) propagate to the caller.

### Public API

20 methods — 4 per resource type:

```
create_deployment / delete_deployment / get_deployment / list_deployments
create_service    / delete_service    / get_service    / list_services
create_pvc        / delete_pvc        / get_pvc        / list_pvcs
create_secret     / delete_secret     / get_secret     / list_secrets
create_config_map / delete_config_map / get_config_map / list_config_maps
```

All `list_*` methods accept an optional `label_selector` string for filtering.

### Known limitations

- Kubeconfig is loaded once at startup. Credential rotation requires a restart.
- Malformed manifests return `ApiException(422)` which propagates to the caller — the wrapper does not validate manifests.
- PVC deletion is asynchronous due to the `kubernetes.io/pvc-protection` finalizer. The resource stays in `Terminating` state briefly after `delete_pvc` returns.

---

## Testing for Reviewers

### Prerequisites

1. Install dependencies from the `api/` directory:
   ```bash
   uv sync
   ```

2. Set the kubeconfig env var pointing at the dev cluster:
   ```
   K8S_KUBECONFIG_PATH=C:\path\to\kubeconfig
   ```
   Add this to your `.env` file or pass it inline.

3. Confirm the `agent-farm` namespace exists and your kubeconfig user has permissions:
   ```bash
   kubectl auth can-i create deployments -n agent-farm
   kubectl auth can-i create secrets -n agent-farm
   ```

### Unit tests (no cluster required)

```bash
cd api
pytest tests/unit/test_kubernetes_client.py -v
```

Expected: 8 passed. No network calls are made — kubernetes config loading is patched and all API calls go to in-process fakes.

### Integration tests (cluster required)

Open a watch terminal to observe resources being created and deleted live:

```bash
kubectl get all,pvc,secret,cm -n agent-farm -w
```

Run the tests:

```bash
cd api
pytest tests/integration/test_kubernetes_client.py -v
```

Expected: 11 passed.

What gets created in `agent-farm` during the run (all labelled `test-run-id=<8chars>`):

| Resource | Name pattern |
|---|---|
| Deployment | `test-dep-<id>` |
| Deployment | `test-dep-idem-<id>` |
| Service | `test-svc-<id>` |
| PVC | `test-pvc-<id>` |
| Secret | `test-sec-<id>` |
| ConfigMap | `test-cm-<id>` |

All are deleted by the autouse session fixture after the run. If the process is hard-killed, clean up manually:

```bash
kubectl delete deployment,service,pvc,secret,configmap -n agent-farm -l test-run-id=<id>
```
