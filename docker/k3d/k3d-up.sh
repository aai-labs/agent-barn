#!/usr/bin/env bash
# Spin up the local k3d dev environment:
#   1. litellm-db + litellm  (Docker compose, profile k3d)
#   2. agentfarm-dev k3d cluster  (k3s in Docker, no host k3d install needed)
#   3. Write .k3d/kubeconfig-host.yaml (kubectl/helm/dev-api on the host) and
#      .k3d/kubeconfig-internal.yaml (the API container, via host.docker.internal)
#
# Required in .env (auto-sourced):
#   OPENROUTER_API_KEY   — passed to litellm
#   LITELLM_MASTER_KEY   — litellm admin key; must be a stable value (required)
#
# Ports on localhost:
#   7070  — LiteLLM proxy
#   16443 — k8s API server

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Auto-source .env so you don't have to export vars manually.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${REPO_ROOT}/.env"
  set +a
fi

# Overridable so a second worktree can run its own cluster alongside the first
# (the defaults are the single-cluster values this flow has always used).
CLUSTER="${K3D_CLUSTER:-agentfarm-dev}"
K8S_API_PORT="${K3D_API_PORT:-16443}"
LITELLM_HOST_PORT="${LITELLM_PORT:-7070}"
# Host port the ingest API is reachable on, for the telemetry pods push back to.
# Kept in step with INGEST_PORT in compose.yml and the Makefile.
INGEST_HOST_PORT="${INGEST_PORT:-8001}"
NAMESPACE="${K8S_NAMESPACE:-agent-farm}"
KUBECONFIG_DIR="${REPO_ROOT}/.k3d"
KUBECONFIG_HOST="${KUBECONFIG_DIR}/kubeconfig-host.yaml"
KUBECONFIG_INTERNAL="${KUBECONFIG_DIR}/kubeconfig-internal.yaml"
COMPOSE="docker compose -f ${REPO_ROOT}/compose.yml --profile k3d"

# ── helpers ───────────────────────────────────────────────────────────────────

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; exit 1; }
step()   { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

# ── checks ────────────────────────────────────────────────────────────────────

step "Checking dependencies"
command -v docker >/dev/null 2>&1 || red "docker not found"
[[ -n "${OPENROUTER_API_KEY:-}" ]] || red "OPENROUTER_API_KEY is not set — add it to .env"
# LiteLLM persists issued keys in its Postgres and (with no separate salt key)
# encrypts them with the master key, so the key must stay stable across runs.
# Require it rather than generating a throwaway that changes every run and
# breaks agents created under a previous key.
[[ -n "${LITELLM_MASTER_KEY:-}" ]] || red "LITELLM_MASTER_KEY is not set — add a stable value to .env, e.g. LITELLM_MASTER_KEY=sk-\$(openssl rand -hex 16)"
green "  docker present"

# ── litellm-db + litellm (compose) ───────────────────────────────────────────

step "Starting litellm-db and litellm (compose profile k3d)"
${COMPOSE} up -d litellm-db litellm
green "  litellm-db and litellm started"

# ── k3d cluster ───────────────────────────────────────────────────────────────

step "Building k3d-runner image"
${COMPOSE} build k3d-runner
green "  k3d-runner ready"

step "k3d cluster '${CLUSTER}'"
if ${COMPOSE} run --rm k3d-runner k3d cluster list 2>/dev/null \
    | awk 'NR>1{print $1}' | grep -qx "${CLUSTER}"; then
  # Exists, but `cluster-down` may have stopped it — start is a no-op when it is
  # already running, and the steps below need a reachable API server.
  yellow "  Cluster already exists — starting it if stopped"
  ${COMPOSE} run --rm k3d-runner k3d cluster start "${CLUSTER}" >/dev/null
  green "  Cluster running"
else
  echo "  Creating cluster…"
  # --tls-san host.docker.internal: kubeconfig-internal.yaml (below) points the
  # API container at https://host.docker.internal:${K8S_API_PORT} and verifies
  # the server certificate, so that name must be in the cert's SAN list or every
  # request fails with an x509 hostname error. k3d only adds it automatically on
  # Docker Desktop; a native Linux engine needs it passed explicitly.
  ${COMPOSE} run --rm k3d-runner k3d cluster create "${CLUSTER}" \
    --api-port "0.0.0.0:${K8S_API_PORT}" \
    --k3s-arg "--tls-san=host.docker.internal@server:0" \
    --wait
  green "  Cluster created"
fi

# ── kubeconfig ────────────────────────────────────────────────────────────────

step "Writing kubeconfigs → ${KUBECONFIG_DIR}/"
mkdir -p "${KUBECONFIG_DIR}"
# k3d runs inside the k3d-runner container, so it emits a server address the
# container uses to reach the API (0.0.0.0 or host.docker.internal). Emit two
# variants from one fetch: host tools reach the published port on 127.0.0.1;
# the API container reaches it via host.docker.internal (which does not resolve
# outside containers).
raw_kubeconfig="$(${COMPOSE} run --rm -T k3d-runner k3d kubeconfig get "${CLUSTER}")"
printf '%s\n' "${raw_kubeconfig}" \
  | sed -E "s|https://(0\.0\.0\.0\|host\.docker\.internal):${K8S_API_PORT}|https://127.0.0.1:${K8S_API_PORT}|g" \
  > "${KUBECONFIG_HOST}"
printf '%s\n' "${raw_kubeconfig}" \
  | sed -E "s|https://(0\.0\.0\.0\|127\.0\.0\.1):${K8S_API_PORT}|https://host.docker.internal:${K8S_API_PORT}|g" \
  > "${KUBECONFIG_INTERNAL}"
chmod 600 "${KUBECONFIG_HOST}" "${KUBECONFIG_INTERNAL}"
green "  ${KUBECONFIG_HOST} (host tools)"
green "  ${KUBECONFIG_INTERNAL} (API container)"

# ── namespace + litellm secret ────────────────────────────────────────────────
# The API creates agent deployments/secrets/PVCs in NAMESPACE but does not
# create the namespace itself, and it reads the litellm master key from a Secret
# named 'litellm' in that namespace (LiteLLMClient._master_key). Seed both here.
# Uses host kubectl against the just-written kubeconfig (server is 127.0.0.1).

step "Seeding namespace '${NAMESPACE}' and litellm secret"
if command -v kubectl >/dev/null 2>&1; then
  export KUBECONFIG="${KUBECONFIG_HOST}"
  kubectl create namespace "${NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "${NAMESPACE}" create secret generic litellm \
    --from-literal=LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  green "  namespace '${NAMESPACE}' and secret 'litellm' ready"
else
  yellow "  kubectl not found — skipping. Before running agents, create them manually:"
  yellow "    export KUBECONFIG=${KUBECONFIG_HOST}"
  yellow "    kubectl create namespace ${NAMESPACE}"
  yellow "    kubectl -n ${NAMESPACE} create secret generic litellm \\"
  yellow "      --from-literal=LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}"
fi

# ── host alias for in-cluster pods (native Linux) ─────────────────────────────
# Agent pods reach the host (LiteLLM on :7070, etc.) via host.docker.internal.
# On Docker Desktop that name already resolves inside pods through Docker's
# embedded DNS. A native Linux docker engine injects nothing, so map it to the
# cluster network's gateway (the host) via the k3s coredns-custom mechanism.

step "Ensuring pods can reach the host (host.docker.internal)"
docker_os="$(docker info -f '{{.OperatingSystem}}' 2>/dev/null || true)"
if [[ "${docker_os}" == *"Docker Desktop"* ]]; then
  green "  Docker Desktop resolves host.docker.internal in-cluster — nothing to do"
elif ! command -v kubectl >/dev/null 2>&1; then
  yellow "  kubectl not found — on native Linux, agents can't resolve"
  yellow "  host.docker.internal until a CoreDNS entry is added for it."
else
  host_ip="$(docker network inspect "k3d-${CLUSTER}" \
    -f '{{range .IPAM.Config}}{{if .Gateway}}{{.Gateway}} {{end}}{{end}}' 2>/dev/null \
    | awk '{print $1}' || true)"
  [[ -n "${host_ip}" ]] || red "could not determine the host IP for network 'k3d-${CLUSTER}'"
  export KUBECONFIG="${KUBECONFIG_HOST}"
  kubectl -n kube-system apply -f - >/dev/null <<COREDNS
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
data:
  host-docker-internal.server: |
    host.docker.internal:53 {
      hosts {
        ${host_ip} host.docker.internal
      }
    }
COREDNS
  kubectl -n kube-system rollout restart deployment coredns >/dev/null 2>&1 || true
  green "  host.docker.internal → ${host_ip} (CoreDNS entry added for Linux)"
fi

# ── summary ───────────────────────────────────────────────────────────────────

# Prints a boxed row padded to the border width, measuring visible width only
# (ANSI color/bold codes are stripped before computing the pad) so port numbers
# of any length and bold spans still land the right border flush.
box_line() {
  local text="$1" visible pad
  visible="$(printf '%s' "$text" | sed -E 's/\x1b\[[0-9;]*m//g')"
  pad=$((52 - ${#visible}))
  (( pad < 0 )) && pad=0
  printf "\033[32m|\033[0m  %s%*s\033[32m|\033[0m\n" "$text" "$pad" ""
}

printf '\n'
green "+------------------------------------------------------+"
box_line "k3d dev environment ready"
green "+------------------------------------------------------+"
box_line "LiteLLM   -> $(printf '\033[1mhttp://127.0.0.1:%s\033[0m' "${LITELLM_HOST_PORT}")"
box_line "k8s API   -> $(printf '\033[1mhttps://127.0.0.1:%s\033[0m' "${K8S_API_PORT}")"
box_line "kubeconfig -> .k3d/kubeconfig-host.yaml"
green "+------------------------------------------------------+"
printf '\n'
printf "  export KUBECONFIG=%s\n" "${KUBECONFIG_HOST}"
printf "  kubectl get pods -A\n\n"
printf "  To run the API in Docker (make up) against this cluster, add to .env:\n"
printf "    API_K8S_KUBECONFIG_PATH=/app/.k3d/kubeconfig-internal.yaml\n\n"
printf "  Agents in k3d reach LiteLLM via:\n"
printf "  http://host.docker.internal:%s\n\n" "${LITELLM_HOST_PORT}"
printf "  Agents push telemetry back to the ingest API via:\n"
printf "  http://host.docker.internal:%s/ingest/v1\n" "${INGEST_HOST_PORT}"
printf "    make up         → served by the api container (port published)\n"
printf "    make dev-api    → starts ingest alongside the main app automatically\n\n"
