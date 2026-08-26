#!/usr/bin/env bash
# One-command local dev stack: validates .env, brings up the k3d cluster +
# LiteLLM, loads agent base images (skipping any already in the cluster),
# runs migrations, then starts db/redis/api/worker/communications/ui in Docker with hot
# reload.
#
# Usage:
#   ./run.sh            start everything, then follow logs (Ctrl-C detaches;
#                       the stack keeps running)
#   ./run.sh --detach   start everything, detached (no logs)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

FOLLOW_LOGS=true
for arg in "$@"; do
  case "$arg" in
    --detach) FOLLOW_LOGS=false ;;
    *) echo "Unknown option: $arg (usage: ./run.sh [--detach])" >&2; exit 1 ;;
  esac
done

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
step()   { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

COMPOSE="docker compose -f compose.yml"

# ── dependencies ─────────────────────────────────────────────────────────────

step "Checking dependencies"
command -v docker >/dev/null 2>&1 || red "docker not found — install Docker Desktop (or another engine) first"
docker info >/dev/null 2>&1 || red "Docker daemon isn't running — start Docker and retry"
green "  docker present and running"

# ── .env ──────────────────────────────────────────────────────────────────────

step "Checking .env"
if [[ ! -f .env ]]; then
  cp .env.spec .env
  red ".env didn't exist — created it from .env.spec. Fill in the required values below and re-run ./run.sh"
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# Everything needed to boot the containers (compose.yml's `:?` vars) plus
# everything needed to actually start an agent — the point of this script is
# to fail loudly here rather than partway through, or worse, at agent-start.
required_vars=(
  POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT
  SECRET_SIGNING_KEY PLATFORM_ADMIN_CREDENTIALS ENVIRONMENT UI_APP_URL API_PORT
  AGENT_TOKEN_ENCRYPTION_KEY
  OPENROUTER_API_KEY LITELLM_MASTER_KEY GH_TOKEN OPENCLAW_IMAGE HERMES_IMAGE
)
missing=()
for var in "${required_vars[@]}"; do
  [[ -n "${!var:-}" ]] || missing+=("$var")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  yellow "Missing required values in .env:"
  for var in "${missing[@]}"; do echo "  - $var"; done
  red "See .env.spec for what each one is and how to generate it, then re-run ./run.sh"
fi
green "  all required values set"

# ── k3d cluster + litellm ─────────────────────────────────────────────────────

step "Starting k3d cluster + LiteLLM"
bash docker/k3d/k3d-up.sh

step "Loading agent base images (skips any already in the cluster)"
bash docker/k3d/k3d-load-images.sh

# The API container needs the in-container kubeconfig path; wire it into .env
# so this stays a one-command flow instead of a manual follow-up step.
if ! grep -q '^API_K8S_KUBECONFIG_PATH=/app/\.k3d/kubeconfig-internal\.yaml$' .env; then
  grep -q '^API_K8S_KUBECONFIG_PATH=' .env \
    && sed -i.bak '/^API_K8S_KUBECONFIG_PATH=/d' .env && rm -f .env.bak
  echo 'API_K8S_KUBECONFIG_PATH=/app/.k3d/kubeconfig-internal.yaml' >> .env
  green "  set API_K8S_KUBECONFIG_PATH in .env"
else
  green "  already set"
fi

# ── app stack ─────────────────────────────────────────────────────────────────

step "Starting db + redis"
${COMPOSE} up -d --wait db redis

step "Running database migrations"
${COMPOSE} build api
${COMPOSE} run --rm --no-deps --workdir /app/api api python -m alembic upgrade head

step "Building and starting api, worker, communications, ui"
${COMPOSE} up -d --build api worker communications ui

# Prints a boxed row padded to the border width, measuring visible width only
# (ANSI color/bold codes stripped before computing the pad) so values of any
# length still land the right border flush.
box_line() {
  local text="$1" visible pad
  visible="$(printf '%s' "$text" | sed -E 's/\x1b\[[0-9;]*m//g')"
  pad=$((52 - ${#visible}))
  (( pad < 0 )) && pad=0
  printf "\033[32m|\033[0m  %s%*s\033[32m|\033[0m\n" "$text" "$pad" ""
}

printf '\n'
green "+------------------------------------------------------+"
box_line "Agent Barn is running"
green "+------------------------------------------------------+"
box_line "UI  -> $(printf '\033[1mhttp://localhost:3000\033[0m')"
box_line "API -> $(printf '\033[1mhttp://localhost:%s\033[0m' "${API_PORT}")"
box_line "Communications -> $(printf '\033[1mhttp://localhost:%s\033[0m' "${COMMUNICATIONS_PORT:-8002}")"
green "+------------------------------------------------------+"
printf '\n'
echo "Log in with PLATFORM_ADMIN_CREDENTIALS from .env."
echo "Stop with: ./stop.sh or 'make stop'   (./stop.sh --clean or 'make stop-clean' also deletes the k3d cluster; volumes are never touched)"

if [[ "$FOLLOW_LOGS" == true ]]; then
  step "Following logs (Ctrl-C detaches; the stack keeps running)"
  ${COMPOSE} logs -f
fi
