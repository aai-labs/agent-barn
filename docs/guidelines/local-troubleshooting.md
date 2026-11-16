# Local startup troubleshooting

Symptoms you're likely to hit once, with the actual cause.

<details>
<summary><b>API exits at startup with <code>500: Error while initializing startup data</code></b></summary>

Scroll up in the log for the real error. The usual cause is the password in
`PLATFORM_ADMIN_CREDENTIALS` failing the API's own policy (≥8 characters, upper,
lower, digit) while bootstrapping the platform admin.

</details>

<details>
<summary><b>Containerized API can't reach the cluster: <code>x509: certificate is valid for 127.0.0.1, ... not host.docker.internal</code></b></summary>

`kubeconfig-internal.yaml` dials the API server by that hostname and verifies the
certificate, so the name has to be in the cert's SAN list. A cluster **created
before this was fixed** may carry the old certificate — `./stop.sh --clean` then
`./run.sh` reissues it. Host mode (`make dev-api`) is immune because it connects
to `127.0.0.1`.

</details>

<details>
<summary><b>Starting an agent fails with <code>Invalid kube-config file. No configuration found.</code></b></summary>

The configured kubeconfig path doesn't resolve to a real file — either
`API_K8S_KUBECONFIG_PATH`/`K8S_KUBECONFIG_PATH` is unset, or it's a relative path
resolved against the wrong working directory. `run.sh` sets
`API_K8S_KUBECONFIG_PATH` for you; in native mode `K8S_KUBECONFIG_PATH` must be
relative to `api/` (the directory `make dev-api` runs from) or absolute. Verify
inside the container:

```bash
docker exec aai_api ls -l "$(grep '^API_K8S_KUBECONFIG_PATH=' .env | cut -d= -f2-)"
```

It must be `/app/.k3d/kubeconfig-internal.yaml` — `compose.yml` mounts `./.k3d`
read-only at `/app/.k3d`.

</details>

<details>
<summary><b>Agent pod stuck in <code>ErrImagePull</code> / <code>ImagePullBackOff</code></b></summary>

The base image for that tag isn't in _that_ cluster. Pods run
`imagePullPolicy=IfNotPresent` against a private registry, so an image that was
never imported cannot be pulled. Compare what's in the cluster against what the
API asks for:

```bash
docker exec k3d-${K3D_CLUSTER:-agentfarm-dev}-server-0 crictl images | grep -E 'openclaw|hermes'
grep -E '^(OPENCLAW|HERMES)_IMAGE=' .env
```

Fix by running `./run.sh` again (it reloads any image missing from the cluster),
or `bash docker/k3d/k3d-load-images.sh` directly with the same `K3D_CLUSTER`.

A second, less obvious cause: an image that _was_ imported can still disappear
later. Imported images are unreferenced whenever no agent is running one, and
kubelet garbage-collects unreferenced images under disk pressure (seen at
`usage=87 highThreshold=85` on a constrained host). With
`imagePullPolicy=IfNotPresent` against a private registry and no pull secret
seeded locally, a GC'd image can't be re-pulled — only reimported.
`docker system df` / `docker stats --no-stream` will show whether disk pressure
is the actual trigger before you re-run the fix above.

</details>

<details>
<summary><b>Warning <code>FailedToRetrieveImagePullSecret (registry-pull-secret)</code> repeating on a pod</b></summary>

Expected locally and harmless on its own — the local flow imports images instead
of pulling, and nothing seeds that secret. It becomes the real error only when
the image is genuinely absent, in which case you'll also see `ErrImagePull`
above.

</details>

<details>
<summary><b>Agent pod <code>CrashLoopBackOff</code> with <code>OOMKilled</code> / exit code 137</b></summary>

Hermes and OpenClaw pods request `320Mi` and have a `1Gi` memory limit. Inspect
the pod with `kubectl -n agent-farm describe pod POD_NAME` to see whether it
hit that limit. Exit code 137 can also result from memory pressure on the k3d
node or Docker VM; check `docker stats --no-stream` and the Docker Desktop
memory allocation too.

</details>

<details>
<summary><b>Agent runs but never answers, or its conversations and tool calls stay empty</b></summary>

Both paths go through the host, so a loopback address in `.env` resolves to the
pod itself. `AGENT_LITELLM_BASE_URL` must be
`http://host.docker.internal:<litellm port>` — it's handed to the pod as
`LITELLM_PROXY_TARGET` and used by the in-pod proxy on `:8090` that the runtime
actually talks to. For empty activity, check ingest is reachable (see [runtime telemetry](../../README.md#local-kubernetes-k3d)).

</details>

<details>
<summary><b>A base-image build crawls or times out fetching Debian packages</b></summary>

The default archive CDN has likely handed you a degraded edge (seen at ~30KB/s,
stalling the build for over an hour). Point the build at another full mirror — it
must carry both `/debian` and `/debian-security`:

```bash
APT_MIRROR=mirror.csclub.uwaterloo.ca bash docker/k3d/k3d-load-images.sh
```

</details>
