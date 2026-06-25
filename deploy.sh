#!/usr/bin/env bash
# Deploy agent-farm to a Kubernetes cluster with helmfile.
#
# Reads all configuration from .env.deploy (copy .env.deploy.spec and fill it
# in). Ships alongside helmfile.yaml.gotmpl and the helm/ charts; run it from that
# directory. Requires helmfile, helm and the helm-diff plugin.
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-.env.deploy}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found. Copy .env.deploy.spec to $ENV_FILE and fill it in." >&2
  exit 1
fi

for bin in helmfile kubectl; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: $bin not found on PATH." >&2
    exit 1
  fi
done

# Export everything defined in the env file so helmfile's `env "..."` can read it.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${KUBECONFIG:?set KUBECONFIG in $ENV_FILE}"

# Kubeconfig the API pod uses to manage agent workloads. Defaults to the same
# kubeconfig used for this deploy; the API rewrites the server host to the
# in-cluster API endpoint at runtime, so a loopback host (e.g. k3s's 127.0.0.1)
# is fine. Override in the env file only to give the pod a different identity.
: "${POD_KUBECONFIG_B64:=$(base64 "$KUBECONFIG" | tr -d '\n')}"
export POD_KUBECONFIG_B64

# Cluster prerequisites not owned by any helm release: the agent-farm-user
# ServiceAccount + RBAC that the API's litellm-key pre-install Job runs as.
# Idempotent — a no-op on clusters where it already exists.
kubectl apply -f k8s/agent-farm-user.yaml

helmfile -f helmfile.yaml.gotmpl sync --wait
