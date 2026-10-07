#!/usr/bin/env bash
# Install the real monitoring chart (Prometheus, Alertmanager, Grafana) into the
# local k3d cluster, so the Resource usage views have data to show:
#   1. Writes a PROMETHEUS_PASSWORD to .env if there is none
#   2. Applies k8s/agent-farm-user.yaml (Prometheus and kube-state-metrics run as
#      that ServiceAccount, which a fresh k3d cluster does not have)
#   3. helm upgrade --install monitoring helm/monitoring
#
# It is the chart the deploy installs, not a copy of its config, so the scrape
# jobs and their labels cannot drift from what production runs.
#
# Unlike the rest of the k3d flow this needs helm and kubectl on the host: the
# k3d-runner helper container has neither, and cannot reach the cluster API.
#
# Safe to run again; it upgrades in place and keeps the password.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

NAMESPACE="${K8S_NAMESPACE:-agent-farm}"
KUBECONFIG_HOST="${REPO_ROOT}/.k3d/kubeconfig-host.yaml"
PROMETHEUS_HOST_PORT="${PROMETHEUS_PORT:-9090}"

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; exit 1; }
step()   { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

sha256_hex() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi
}

# ── checks ────────────────────────────────────────────────────────────────────

step "Checking dependencies"
command -v helm >/dev/null 2>&1 || red "helm not found — install it (https://helm.sh/docs/intro/install/); this step needs it on the host"
command -v kubectl >/dev/null 2>&1 || red "kubectl not found — install it; this step needs it on the host"
command -v openssl >/dev/null 2>&1 || red "openssl not found"
[[ -f "${KUBECONFIG_HOST}" ]] || red "${KUBECONFIG_HOST} not found — run ./run.sh (or docker/k3d/k3d-up.sh) first"
# k8s/agent-farm-user.yaml is written for this namespace only.
[[ "${NAMESPACE}" == "agent-farm" ]] || red "K8S_NAMESPACE is '${NAMESPACE}', but k8s/agent-farm-user.yaml is pinned to 'agent-farm'"
export KUBECONFIG="${KUBECONFIG_HOST}"
green "  helm, kubectl and the k3d kubeconfig are present"

# ── password ──────────────────────────────────────────────────────────────────
# Prometheus requires basic auth (agent pods share the namespace and could
# otherwise query it). The API reads the same password from .env.

step "Monitoring password"
if [[ -z "${PROMETHEUS_PASSWORD:-}" ]]; then
  PROMETHEUS_PASSWORD="$(openssl rand -hex 16)"
  touch "${REPO_ROOT}/.env"
  # Same delete-and-append pattern run.sh uses for API_K8S_KUBECONFIG_PATH.
  if grep -q '^PROMETHEUS_PASSWORD=' "${REPO_ROOT}/.env"; then
    sed -i.bak '/^PROMETHEUS_PASSWORD=/d' "${REPO_ROOT}/.env" && rm -f "${REPO_ROOT}/.env.bak"
  fi
  echo "PROMETHEUS_PASSWORD=${PROMETHEUS_PASSWORD}" >> "${REPO_ROOT}/.env"
  green "  generated PROMETHEUS_PASSWORD and saved it to .env"
else
  green "  using PROMETHEUS_PASSWORD from .env"
fi
# The chart embeds the password in the config reloader URL, so it must be plain
# letters and digits.
[[ "${PROMETHEUS_PASSWORD}" =~ ^[A-Za-z0-9]{12,}$ ]] \
  || red "PROMETHEUS_PASSWORD in .env must be at least 12 letters and digits — remove it and re-run to generate one"

# ── ServiceAccount ────────────────────────────────────────────────────────────

step "ServiceAccount agent-farm-user"
kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}" >/dev/null
kubectl apply -f "${REPO_ROOT}/k8s/agent-farm-user.yaml" >/dev/null
green "  agent-farm-user and its read Role are in place"

# ── chart ─────────────────────────────────────────────────────────────────────

step "Building chart dependencies"
helm repo add --force-update prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add --force-update grafana https://grafana.github.io/helm-charts >/dev/null
helm dependency build "${REPO_ROOT}/helm/monitoring" >/dev/null
green "  dependencies ready"

# What helmfile derives from MONITORING_WEB_PASSWORD (helmfile.yaml.gotmpl, the
# monitoring release). The probes and Prometheus's config reloader only take literal
# values, and the chart's own checks fail the install if these drift from the password.
basic="Basic $(printf 'monitoring:%s' "${PROMETHEUS_PASSWORD}" | base64 | tr -d '\n')"
checksum="$(printf '%s' "${PROMETHEUS_PASSWORD}" | sha256_hex)"

secret_values="$(mktemp)"
trap 'rm -f "${secret_values}"' EXIT
chmod 600 "${secret_values}"
cat > "${secret_values}" <<EOF
webAuth:
  password: "${PROMETHEUS_PASSWORD}"
prometheus:
  server:
    probeHeaders:
      - name: Authorization
        value: "${basic}"
  configmapReload:
    reloadUrl: "http://monitoring:${PROMETHEUS_PASSWORD}@127.0.0.1:9090/-/reload"
  alertmanager:
    livenessProbe:
      httpGet:
        httpHeaders:
          - name: Authorization
            value: "${basic}"
    readinessProbe:
      httpGet:
        httpHeaders:
          - name: Authorization
            value: "${basic}"
grafana:
  podAnnotations:
    checksum/web-auth: "${checksum}"
EOF

step "Installing the monitoring release into '${NAMESPACE}'"
# --no-hooks skips the LiteLLM metrics-key Job, which waits for http://litellm:4000.
# LiteLLM runs in Docker Compose here, not in the cluster, so that wait would fail.
# Prometheus mounts that Secret as optional, so the litellm scrape job simply finds
# no targets.
helm upgrade --install monitoring "${REPO_ROOT}/helm/monitoring" \
  --namespace "${NAMESPACE}" \
  --no-hooks --wait --timeout 5m \
  -f "${REPO_ROOT}/docker/k3d/monitoring-values.yaml" \
  -f "${secret_values}" >/dev/null
green "  release 'monitoring' is running"

cat <<EOF

Next:
  1. make forward-prometheus          keep it running; the API reaches Prometheus through it
  2. docker compose up -d api         recreate the API so it picks up PROMETHEUS_PASSWORD
  3. stop and start an agent          its healthz script only reports CPU and memory after a restart

Prometheus will be at http://localhost:${PROMETHEUS_HOST_PORT} (user 'monitoring', password in .env).
Grafana: kubectl -n ${NAMESPACE} port-forward svc/monitoring-grafana 3001:80
Running the API on the host instead of Docker? Add PROMETHEUS_URL=http://localhost:${PROMETHEUS_HOST_PORT} to .env.
EOF
