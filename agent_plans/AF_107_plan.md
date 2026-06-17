# AF-107: Replace kubectl subprocess calls with Kubernetes Python SDK

## Goal

Remove the `kubectl` binary dependency from the API Docker image. All Kubernetes operations must go through the official Python SDK (`kubernetes` package) instead of spawning `kubectl` subprocesses.

**Acceptance criteria:**
1. Backend uses K8s API through the Python SDK, not subprocess kubectl
2. kubectl is removed from the API Docker image

---

## What changed

### Files modified

1. **`api/infrastructure/kubernetes/client.py`** — All kubectl subprocess calls replaced with SDK equivalents
2. **`api/Dockerfile`** — Removed the `RUN` block that downloaded and installed kubectl (curl, ca-certificates, kubectl binary)

### Code changes in `client.py`

**Removed imports:** `socket`, `subprocess`, `time`
**Added imports:** `from kubernetes.stream import portforward as k8s_portforward`, `from kubernetes.stream import stream as k8s_stream`

**Deleted methods:**
- `_kubectl_args` — built kubectl CLI args
- `_free_local_port` — found free TCP port for subprocess port-forward
- `_wait_for_local_port` — polled until subprocess port-forward was ready

**Replaced methods:**

| Method | Old (subprocess) | New (SDK) |
|--------|-----------------|-----------|
| `exec_command` | `subprocess.run(["kubectl", "exec", ...])` | `k8s_stream(connect_get_namespaced_pod_exec, ...)` with `_preload_content=False` |
| `_fetch_agent_healthz_via_port_forward` | Spawned `kubectl port-forward`, waited for TCP, made HTTP request, killed process | `k8s_portforward(connect_get_namespaced_pod_portforward, ...)` + `pf.socket()` + `conn.sock = sock` |
| `_proxy_to_agent_via_port_forward` | Same subprocess pattern with dynamic port | Same SDK pattern with dynamic port |

**Added field:** `_stream_core_v1: client.CoreV1Api` — a separate CoreV1Api backed by its own ApiClient, used exclusively for stream/portforward calls.

### Method signatures & behavior — unchanged

All three replaced methods keep identical signatures, return types, and error types (`RuntimeError`). Callers in `agents/service.py`, `conversations/service.py`, and `tool_calls/sync_service.py` are untouched. Tests mock at the method level and need no changes.

---

## Issues encountered and root causes

### Issue 1: Thread-safety — monkey-patching race condition

**Symptom:** `ApiValueError: Missing required parameter 'ports'` on `delete_namespaced_service` when deleting an agent while healthz polling was running.

**Root cause:** The SDK's `stream()` and `portforward()` helpers temporarily replace `api_client.request` with a WebSocket handler. When a shared `CoreV1Api` instance is used by concurrent FastAPI threads, one thread's portforward monkey-patches the `request` method that another thread's `delete_service` call then hits.

**Fix:** Created a separate `_stream_core_v1` field with its own `ApiClient`, isolating the monkey-patching from the shared `_core_v1` used by regular CRUD operations.

```python
# In __post_init__:
if self.config.k8s_kubeconfig_path:
    stream_api_client = k8s_config.new_client_from_config(
        config_file=self.config.k8s_kubeconfig_path
    )
else:
    stream_api_client = client.ApiClient()
self._stream_core_v1 = client.CoreV1Api(api_client=stream_api_client)
```

All `k8s_stream` and `k8s_portforward` calls use `self._stream_core_v1` instead of `self._core_v1`.

### Issue 2: 403 Forbidden on exec and portforward

**Symptom:** `Handshake status 403 Forbidden` — `cannot get resource "pods/exec"` and `cannot get resource "pods/portforward"` for `system:serviceaccount:agent-farm:agent-farm-user`.

**Root cause:** HTTP-verb → RBAC-verb mismatch.

- `kubectl exec` / `kubectl port-forward` use **SPDY protocol** which starts with an **HTTP POST**. POST maps to RBAC verb **`create`** on the subresource.
- The Python SDK's `stream()`/`portforward()` helpers use **WebSocket protocol** which always starts with an **HTTP GET** handshake (per RFC 6455). GET maps to RBAC verb **`get`** on the subresource.
- The ServiceAccount `agent-farm-user` only had **`create`** granted on `pods/exec`, `pods/portforward`, and `pods/attach`. It did **not** have **`get`**.

**Why `connect_post_*` doesn't help:** The SDK method name (`connect_get_*` vs `connect_post_*`) only changes the HTTP method parameter passed to `call_api`. But the monkey-patching replaces the request handler with a WebSocket handler that ALWAYS sends HTTP GET for the handshake. The `_method` parameter is received but ignored by `websocket_call`/`portforward_call`.

**Why `kubectl auth can-i get pods/exec` returned `yes` (false positive):** `kubectl auth can-i` does not reliably evaluate subresources. When you pass `pods/exec`, it effectively evaluates against the parent `pods` resource (which the SA does have `get` on), returning `yes` even though no `get` grant exists on the `pods/exec` subresource. The authoritative checks are:
- `kubectl auth can-i --list` — shows `pods/exec [create]` only, no `get`
- Raw `SelfSubjectAccessReview` — `get = false`, `create = true`

**Fix:** Grant `get` verb on the subresources in the cluster RBAC:

```yaml
- apiGroups: [""]
  resources: ["pods/exec", "pods/portforward", "pods/attach"]
  verbs: ["get", "create"]
```

This was applied to the cluster RBAC for `agent-farm-user`.

---

## Current state of the code

### `api/infrastructure/kubernetes/client.py` — complete

```python
# Imports
from kubernetes.stream import portforward as k8s_portforward
from kubernetes.stream import stream as k8s_stream

# Fields
_apps_v1: client.AppsV1Api          # regular CRUD
_core_v1: client.CoreV1Api           # regular CRUD
_stream_core_v1: client.CoreV1Api    # exec/portforward only (isolated ApiClient)

# __post_init__ creates _stream_core_v1 with:
#   - new_client_from_config() for kubeconfig path (avoids deep-copy auth issues)
#   - client.ApiClient() for in-cluster (bearer tokens survive deep copy)

# exec_command: uses k8s_stream with _preload_content=False, reads channels 1/2,
#   checks ws.returncode, raises RuntimeError on failure (same contract as before)

# _fetch_agent_healthz_via_port_forward: uses k8s_portforward + pf.socket(8081)
# _proxy_to_agent_via_port_forward: uses k8s_portforward + pf.socket(port)
```

### `api/Dockerfile` — complete

kubectl binary installation block removed. Image no longer needs curl, ca-certificates, or kubectl.

### RBAC — complete

`get` verb added to `pods/exec`, `pods/portforward`, `pods/attach` for `agent-farm-user` SA.

---

## Callers (unchanged)

| File | Method | What it executes |
|------|--------|-----------------|
| `agents/service.py:900` | `exec_command` | `openclaw pairing approve` |
| `conversations/service.py:224,235,246,341` | `exec_command` | `cat`, `hermes sessions export` |
| `tool_calls/sync_service.py:66,98,134,205` | `exec_command` | `find`, `cat`, `hermes sessions export`, `tail` |
| `agents/service.py:1038` | `fetch_agent_healthz` | HTTP to service, fallback to portforward |
| Multiple proxy routes | `proxy_to_agent` | HTTP to service, fallback to portforward |

All callers mock `exec_command` at the method level in tests. No test changes needed.

---

## How the SDK exec/portforward works (reference)

### exec via `k8s_stream`

1. `stream()` in `stream.py` calls `_websocket_request(websocket_call, None, api_method, *args, **kwargs)`
2. `_websocket_request` saves the original `api_client.request`, replaces it with `functools.partial(websocket_call, configuration, binary=False)`
3. The bound API method (`connect_get_namespaced_pod_exec`) is called, which goes through `api_client.call_api()` → `api_client.__call_api()` → `api_client.request()` (now the WebSocket handler)
4. `websocket_call` converts the URL to `wss://`, extracts the `authorization` header from the headers dict, and calls `create_websocket(configuration, url, headers)`
5. `create_websocket` constructs a `WebSocket` with SSL opts from the configuration, sends headers (including auth), and connects
6. The K8s API server receives the GET + Upgrade: websocket request, checks RBAC verb `get` on `pods/exec`, upgrades to WebSocket
7. With `_preload_content=False`, the raw `WSClient` is returned. Channels: 0=stdin, 1=stdout, 2=stderr, 3=error/status
8. `ws.returncode` parses the YAML status from channel 3

### portforward via `k8s_portforward`

1. Same monkey-patching flow, but `portforward_call` is used instead of `websocket_call`
2. `portforward_call` extracts `ports` from query params, creates WebSocket, returns a `PortForward` object
3. `pf.socket(port)` returns a socket-like object connected to the pod's port through the WebSocket tunnel
4. Setting `conn.sock = sock` on `HTTPConnection` bypasses DNS resolution and TCP connect — traffic goes through the tunnel

### Why `_stream_core_v1` needs its own ApiClient

The monkey-patching (`api_client.request = websocket_call`) is NOT thread-safe. If two threads share the same `api_client`, one thread's portforward call patches `request` while another thread's `delete_service` call hits the patched handler (which expects WebSocket parameters, not REST parameters). Using a separate `ApiClient` isolates the patching.

---

## Verification

1. **Manual test:** Run local API + UI, create/start an agent, verify:
   - Healthz loads (tests portforward fallback)
   - Conversations tab loads channels/messages (tests exec: `hermes sessions export`)
   - Tool calls tab loads (tests exec: `find`, `cat`, `tail`)
   - Agent delete works without errors (tests that CRUD isn't affected by monkey-patching)

2. **Automated tests:**
   - `make check-api` — lint/type checks pass
   - `make test-api` — all existing tests pass (they mock at method level)

3. **Grep verification:**
   - `grep -r "subprocess" api/infrastructure/kubernetes/client.py` → no matches
   - `grep -r "kubectl" api/infrastructure/kubernetes/client.py` → no matches
   - `grep -r "kubectl" api/Dockerfile` → no matches

---

## Key lessons / gotchas for future reference

1. **WebSocket is always HTTP GET.** The Python SDK method name (`connect_get_*` vs `connect_post_*`) is irrelevant — WebSocket RFC 6455 mandates GET for the handshake. RBAC must grant `get` on exec/portforward subresources for the SDK to work.

2. **`kubectl auth can-i` gives false positives on subresources.** Use `kubectl auth can-i --list` or raw `SelfSubjectAccessReview` to verify subresource permissions. `can-i <verb> pods/exec` may evaluate against the parent `pods` resource.

3. **`stream()`/`portforward()` monkey-patch `api_client.request`.** This is not thread-safe. Always use a separate `CoreV1Api` with its own `ApiClient` for stream operations in multi-threaded environments (like FastAPI).

4. **`new_client_from_config()` vs `client.ApiClient()`:** `ApiClient()` with no args uses `Configuration.get_default_copy()` (deep copy). `new_client_from_config()` loads the kubeconfig into a fresh Configuration without deep-copying. Both work for static bearer tokens, but `new_client_from_config` is safer for exec-based auth providers.
