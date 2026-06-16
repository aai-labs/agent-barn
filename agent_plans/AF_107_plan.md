# AF-107 Diagnosis: Kubernetes SDK Exec/Port-Forward Migration

## Summary

The attempted migration from `kubectl` subprocess calls to the Kubernetes Python SDK is not working because the SDK stream helpers are not a drop-in replacement for `kubectl exec` and `kubectl port-forward`.

Changing `connect_get_*` to `connect_post_*` is not the real fix. The Python SDK method name changes, but the underlying WebSocket transport still opens a `GET` upgrade handshake. Kubernetes streaming behavior is more nuanced than normal REST calls, and `kubectl` handles protocol details and fallbacks that the current SDK usage does not.

## Findings

- The app now calls `connect_post_namespaced_pod_exec` and `connect_post_namespaced_pod_portforward`, but `kubernetes.stream.stream()` / `portforward()` monkey-patch the SDK request layer.
- The SDK WebSocket helper receives the generated method's HTTP verb but effectively ignores it when creating the WebSocket connection.
- The underlying `websocket-client` handshake is hardcoded as `GET ... HTTP/1.1` with `Upgrade: websocket`.
- Kubernetes modern WebSocket streaming starts as a GET upgrade request, then performs a synthetic `create` authorization check for subresources such as `pods/exec` and `pods/portforward`.
- Therefore, RBAC checks returning `yes` for both `get` and `create` are necessary, but they do not prove the SDK transport is protocol-compatible.
- Existing tests only cover Kubernetes CRUD operations. They do not exercise `exec_command`, healthz via port-forward, or proxying via port-forward.

Relevant references:

- https://kubernetes.io/blog/2024/08/20/websockets-transition/
- https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/4006-transition-spdy-to-websockets

## Likely Root Cause

The root cause is not simple RBAC and not simply "GET vs POST".

The migration removed `kubectl`, but the replacement Python SDK stream/port-forward helpers do not fully match the Kubernetes streaming behavior that `kubectl` provides. In particular, switching from `connect_get_*` to `connect_post_*` does not reliably change the actual WebSocket request behavior, and the SDK defaults may not match the cluster's expected streaming subprotocols.

## Fix Options

### Option A: Restore `kubectl` for exec and port-forward

Recommended short-term fix.

Work estimate: 1-2 hours.

Changes:

- Revert `exec_command` to use `kubectl exec`.
- Revert port-forward fallback methods to use `kubectl port-forward`.
- Add `kubectl` back to `api/Dockerfile`.
- Keep the Kubernetes Python SDK for normal CRUD operations.
- Add targeted smoke/integration coverage for exec and port-forward behavior.

Pros:

- Fastest and lowest risk.
- Matches previous working behavior.
- Lets `kubectl` handle Kubernetes streaming protocol differences.

Cons:

- Keeps the `kubectl` binary in the API image.
- Uses subprocesses for streaming operations.

### Option B: Build a custom Python streaming implementation

Recommended only if removing `kubectl` is a hard requirement.

Work estimate: 1-2 days minimum.

Changes:

- Implement explicit Kubernetes WebSocket handling for exec.
- Handle stdout, stderr, exit-code channels, timeout behavior, and error propagation.
- Implement port-forward channel handling correctly.
- Negotiate the correct Kubernetes WebSocket subprotocols.
- Test against the actual target cluster.

Pros:

- Removes `kubectl` dependency.
- Keeps all Kubernetes behavior in Python code.

Cons:

- Higher implementation risk.
- Port-forward protocol handling is fiddly.
- Requires real-cluster validation, not just unit tests.

### Option C: Hybrid approach

Use SDK for normal CRUD, maybe SDK/custom code for exec, but restore `kubectl` for port-forward.

Work estimate: half day to 1 day.

Pros:

- Reduces some subprocess usage.
- Avoids the hardest part if port-forward is the main pain point.

Cons:

- Mixed behavior is harder to reason about.
- Still requires careful streaming validation.
- Not as clean as either fully restoring `kubectl` or fully implementing streaming.

## Recommendation

Use Option A now: restore `kubectl` for `exec` and `port-forward`, keep the Kubernetes Python SDK for ordinary CRUD operations, and add targeted integration or smoke tests for the streaming paths.

The current pure-SDK replacement is deceptively small in code size but not small in behavior. The reliable fix is hours; the robust no-`kubectl` implementation is days.

## Verification Plan

- Confirm the runtime kubeconfig/token is the same identity used during `kubectl auth can-i` checks.
- Add or run a smoke test for:
  - `exec_command(..., ["cat", ...])`
  - `_fetch_agent_healthz_via_port_forward`
  - `_proxy_to_agent_via_port_forward`
- Verify no 403 occurs for `pods/exec` or `pods/portforward`.
- Run API checks after code changes:
  - `make check-api`
  - `make test-api`
