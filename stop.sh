#!/usr/bin/env bash
# Stop the local dev stack started by ./run.sh.
#
# Usage:
#   ./stop.sh          stop containers; DB/redis data and the k3d cluster survive
#   ./stop.sh --clean  also delete the k3d cluster (agent base images will need
#                       reloading on the next ./run.sh). Volumes are never
#                       touched — DB/redis data always survives.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

CLEAN=false
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=true ;;
    *) echo "Unknown option: $arg (usage: ./stop.sh [--clean])" >&2; exit 1 ;;
  esac
done

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
step()   { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

COMPOSE="docker compose -f compose.yml"
CLUSTER="${K3D_CLUSTER:-agentfarm-dev}"

if [[ "$CLEAN" == true ]]; then
  step "Stopping and removing containers (volumes preserved)"
  ${COMPOSE} --profile k3d down --remove-orphans

  step "Deleting k3d cluster '${CLUSTER}'"
  ${COMPOSE} --profile k3d run --rm k3d-runner k3d cluster delete "${CLUSTER}" || true
  rm -rf .k3d

  green "Clean stop complete (DB/redis volumes preserved) — next ./run.sh rebuilds the cluster and reloads images from scratch."
else
  step "Stopping containers (data and k3d cluster preserved)"
  ${COMPOSE} down

  step "Stopping k3d cluster '${CLUSTER}' and litellm"
  ${COMPOSE} --profile k3d run --rm k3d-runner k3d cluster stop "${CLUSTER}" 2>/dev/null || true
  ${COMPOSE} --profile k3d stop litellm litellm-db

  green "Stopped. Resume with ./run.sh"
fi
