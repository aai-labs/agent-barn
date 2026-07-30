#!/usr/bin/env bash
# Build the openclaw and hermes agent base images locally and import them
# into the running agentfarm-dev k3d cluster.
#
# Required env vars:
#   GH_TOKEN          — GitHub PAT with read access to aai-labs/agent-cli-tools
#                       (https://github.com/aai-labs/agent-cli-tools)
#   OPENCLAW_IMAGE    — fully-qualified image name+tag (from .env)
#   HERMES_IMAGE      — fully-qualified image name+tag (from .env)
#
# Optional:
#   APT_MIRROR        — Debian archive host for the base-image builds. The
#                       default CDN occasionally serves a badly degraded edge
#                       (~30KB/s), which stalls these builds for an hour or
#                       more. Point this at a nearby full mirror to recover.
#                       It must carry both /debian and /debian-security.
#
# Usage:
#   make k3d-load-images              # build + import both
#   TARGET=openclaw make k3d-load-images  # one image only
#   TARGET=hermes   make k3d-load-images
#   APT_MIRROR=mirror.csclub.uwaterloo.ca make k3d-load-images

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
TARGET="${TARGET:-all}"  # all | openclaw | hermes
APT_MIRROR="${APT_MIRROR:-deb.debian.org}"
COMPOSE="docker compose -f ${REPO_ROOT}/compose.yml --profile k3d"

# ── helpers ───────────────────────────────────────────────────────────────────

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; exit 1; }
step()   { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

# ── checks ────────────────────────────────────────────────────────────────────

step "Checking dependencies"
command -v docker >/dev/null 2>&1 || red "docker not found"

[[ -n "${GH_TOKEN:-}" ]]       || red "GH_TOKEN is not set — needed to clone agent-cli-tools"
[[ -n "${OPENCLAW_IMAGE:-}" ]] || red "OPENCLAW_IMAGE is not set — source your .env first"
[[ -n "${HERMES_IMAGE:-}" ]]   || red "HERMES_IMAGE is not set — source your .env first"

# Verify the cluster is running (via the k3d-runner container)
${COMPOSE} run --rm k3d-runner k3d cluster list 2>/dev/null \
  | awk 'NR>1{print $1}' | grep -qx "${CLUSTER}" \
  || red "k3d cluster '${CLUSTER}' is not running — run 'make cluster-up' first"

green "  checks passed"

# ── build ─────────────────────────────────────────────────────────────────────

build_image() {
  local name="$1"
  local dockerfile="$2"
  local context="$3"
  local tag="$4"

  step "Building ${name} → ${tag}"
  if [[ "${APT_MIRROR}" != "deb.debian.org" ]]; then
    green "  using Debian mirror: ${APT_MIRROR}"
  fi
  docker build \
    --secret "id=gh_token,env=GH_TOKEN" \
    --build-arg "APT_MIRROR=${APT_MIRROR}" \
    --file "${REPO_ROOT}/${dockerfile}" \
    --tag  "${tag}" \
    --progress=plain \
    "${REPO_ROOT}/${context}"
  green "  built ${tag}"
}

# ── import into k3d ───────────────────────────────────────────────────────────

import_image() {
  local tag="$1"
  step "Importing ${tag} → k3d cluster '${CLUSTER}'"
  # k3d-runner sees the host Docker daemon via the mounted socket, so it can
  # find the locally built image and stream it into the cluster's containerd.
  ${COMPOSE} run --rm k3d-runner k3d image import "${tag}" --cluster "${CLUSTER}"
  green "  imported"
}

# ── main ──────────────────────────────────────────────────────────────────────

if [[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]]; then
  build_image "openclaw-base" \
    "openclaw-base/Dockerfile" \
    "openclaw-base" \
    "${OPENCLAW_IMAGE}"
  import_image "${OPENCLAW_IMAGE}"
fi

if [[ "${TARGET}" == "all" || "${TARGET}" == "hermes" ]]; then
  build_image "hermes-base" \
    "hermes-base/Dockerfile" \
    "hermes-base" \
    "${HERMES_IMAGE}"
  import_image "${HERMES_IMAGE}"
fi

# ── summary ───────────────────────────────────────────────────────────────────

printf '\n'
green "Images loaded into k3d cluster '${CLUSTER}'."
[[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]] && printf "  openclaw → %s\n" "${OPENCLAW_IMAGE}"
[[ "${TARGET}" == "all" || "${TARGET}" == "hermes"   ]] && printf "  hermes   → %s\n" "${HERMES_IMAGE}"
printf '\n'
printf "Pods will use imagePullPolicy=IfNotPresent (pinned tags) and skip the registry.\n\n"
