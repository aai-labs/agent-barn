#!/usr/bin/env bash
# Spin up the local k3d dev environment:
#   1. litellm-db + litellm  (Docker compose, profile k3d)
#   2. agentfarm-dev k3d cluster  (k3s in Docker, no host k3d install needed)
#   3. Write .k3d/kubeconfig-host.yaml (kubectl/helm/dev-api on the host) and
#      .k3d/kubeconfig-internal.yaml (the API container, via host.docker.internal)
#
# Required in .env (auto-sourced):
#   OPENROUTER_API_KEY   — passed to litellm
#   LITELLM_MASTER_KEY   — litellm auth key (generated + printed if absent)
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

CLUSTER="agentfarm-dev"
K8S_API_PORT=16443
LITELLM_HOST_PORT=7070
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
green "  docker present"

# Generate LITELLM_MASTER_KEY if not provided.
if [[ -z "${LITELLM_MASTER_KEY:-}" ]]; then
  LITELLM_MASTER_KEY="sk-$(openssl rand -hex 16)"
  export LITELLM_MASTER_KEY
  yellow "  Generated LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}"
  yellow "  Add to your .env to keep it stable across restarts."
fi

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
  yellow "  Cluster already exists — skipping creation"
else
  echo "  Creating cluster…"
  ${COMPOSE} run --rm k3d-runner k3d cluster create "${CLUSTER}" \
    --api-port "0.0.0.0:${K8S_API_PORT}" \
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

# ── summary ───────────────────────────────────────────────────────────────────

printf '\n'
green "╔══════════════════════════════════════════════════════╗"
green "║  k3d dev environment ready                           ║"
green "╠══════════════════════════════════════════════════════╣"
printf "\033[32m║\033[0m  LiteLLM   → \033[1mhttp://127.0.0.1:%s\033[0m%s\033[32m║\033[0m\n" \
  "${LITELLM_HOST_PORT}" "$(printf '%*s' $((23 - ${#LITELLM_HOST_PORT})) '')"
printf "\033[32m║\033[0m  k8s API   → \033[1mhttps://127.0.0.1:%s\033[0m%s\033[32m║\033[0m\n" \
  "${K8S_API_PORT}" "$(printf '%*s' $((23 - ${#K8S_API_PORT})) '')"
printf "\033[32m║\033[0m  kubeconfig → .k3d/kubeconfig-host.yaml               \033[32m║\033[0m\n"
green "╚══════════════════════════════════════════════════════╝"
printf '\n'
printf "  export KUBECONFIG=%s\n" "${KUBECONFIG_HOST}"
printf "  kubectl get pods -A\n\n"
printf "  To run the API in Docker (make up) against this cluster, add to .env:\n"
printf "    API_K8S_KUBECONFIG_PATH=/app/.k3d/kubeconfig-internal.yaml\n\n"
printf "  Agents in k3d reach LiteLLM via:\n"
printf "  http://host.docker.internal:%s\n\n" "${LITELLM_HOST_PORT}"
