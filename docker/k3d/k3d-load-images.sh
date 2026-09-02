#!/usr/bin/env bash
# Build the openclaw and hermes agent base images locally (skipping the build
# for any tag already in the cluster or already in the local Docker image
# store) and import them into the running agentfarm-dev k3d cluster.
# ./run.sh calls this automatically; run it directly for a single target or
# to reimport after the cluster was recreated.
#
# Required env vars:
#   OPENCLAW_IMAGE    — fully-qualified image name+tag (from .env)
#   HERMES_IMAGE      — fully-qualified image name+tag (from .env)
#   GH_TOKEN          — GitHub PAT with read access to aai-labs/aai-cli
#                       (https://github.com/aai-labs/aai-cli); only
#                       needed when a build actually has to run.
#
# Optional:
#   APT_MIRROR        — Debian archive host for the base-image builds. The
#                       default CDN occasionally serves a badly degraded edge
#                       (~30KB/s), which stalls these builds for an hour or
#                       more. Point this at a nearby full mirror to recover.
#                       It must carry both /debian and /debian-security.
#
# Usage:
#   bash docker/k3d/k3d-load-images.sh              # build/import both
#   TARGET=openclaw bash docker/k3d/k3d-load-images.sh  # one image only
#   TARGET=hermes   bash docker/k3d/k3d-load-images.sh
#   APT_MIRROR=mirror.csclub.uwaterloo.ca bash docker/k3d/k3d-load-images.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Auto-source .env so you don't have to export vars manually.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

CLUSTER="${K3D_CLUSTER:-agentfarm-dev}"
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

if [[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]]; then
  [[ -n "${OPENCLAW_IMAGE:-}" ]] || red "OPENCLAW_IMAGE is not set — source your .env first"
fi
if [[ "${TARGET}" == "all" || "${TARGET}" == "hermes" ]]; then
  [[ -n "${HERMES_IMAGE:-}" ]] || red "HERMES_IMAGE is not set — source your .env first"
fi
# GH_TOKEN is only needed to build; checked lazily in build_image so a run
# that only needs to import an image already sitting in the local Docker
# image store (see image_available_locally below) doesn't require it.

# The API launches pods from these env-var refs with imagePullPolicy=IfNotPresent,
# while CI publishes each base image under exactly its VERSION tag. A tag that
# doesn't match its VERSION file means building/importing one image and running a
# different one — so fail loudly here rather than at ErrImagePull time.
assert_tag_matches_version() {
  local var_name="$1" image_ref="$2" version_file="$3"
  local want tag
  [[ -f "${REPO_ROOT}/${version_file}" ]] || red "${version_file} not found"
  want="$(tr -d '[:space:]' < "${REPO_ROOT}/${version_file}")"
  tag="${image_ref##*:}"
  # No colon at all (or a bare registry:port with no tag) means no tag was pinned.
  if [[ "${tag}" == "${image_ref}" || "${tag}" == *"/"* ]]; then
    red "${var_name} has no tag — it must end in ':${want}' to match ${version_file}"
  fi
  [[ "${tag}" == "${want}" ]] || red "$(
    printf '%s tag is %s but %s says %s.\n' "${var_name}" "${tag}" "${version_file}" "${want}"
    printf '       Update .env so the tag matches, e.g. %s:%s' "${image_ref%:*}" "${want}"
  )"
}

if [[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]]; then
  assert_tag_matches_version OPENCLAW_IMAGE "${OPENCLAW_IMAGE}" openclaw-base/VERSION
fi
if [[ "${TARGET}" == "all" || "${TARGET}" == "hermes" ]]; then
  assert_tag_matches_version HERMES_IMAGE "${HERMES_IMAGE}" hermes-base/VERSION
fi

# Verify the cluster exists AND is actually running — `k3d cluster list`
# lists a stopped cluster too (SERVERS column reads "0/N"), so checking for
# the name alone lets a stopped cluster pass, then the import fails only
# after minutes spent building.
cluster_line="$(${COMPOSE} run --rm k3d-runner k3d cluster list 2>/dev/null \
  | awk -v c="${CLUSTER}" 'NR>1 && $1==c {print; exit}')"
[[ -n "${cluster_line}" ]] \
  || red "k3d cluster '${CLUSTER}' does not exist — run './run.sh' (or 'bash docker/k3d/k3d-up.sh') first"
running_servers="$(awk '{split($2,a,"/"); print a[1]}' <<<"${cluster_line}")"
[[ "${running_servers}" =~ ^[1-9][0-9]*$ ]] \
  || red "k3d cluster '${CLUSTER}' exists but isn't running (servers: $(awk '{print $2}' <<<"${cluster_line}")) — run './run.sh' (or 'bash docker/k3d/k3d-up.sh') first"

green "  checks passed"

# ── build ─────────────────────────────────────────────────────────────────────

build_image() {
  local name="$1"
  local dockerfile="$2"
  local context="$3"
  local tag="$4"

  [[ -n "${GH_TOKEN:-}" ]] || red "GH_TOKEN is not set — needed to clone aai-cli for the ${name} build"

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

# ── skip check ────────────────────────────────────────────────────────────────

# Tags are pinned to the base image's VERSION file (asserted above), so a tag
# already present in the node's containerd store is byte-for-byte what we'd
# build again — safe to skip the (slow) build+import.
image_loaded_in_cluster() {
  local tag="$1"
  docker exec "k3d-${CLUSTER}-server-0" ctr -n k8s.io images ls -q 2>/dev/null \
    | grep -qF "${tag}"
}

# A tag already in the local Docker image store — built by hand, by a prior
# run, or by CI's publish step — is exactly what build_image would produce,
# so import it directly instead of demanding GH_TOKEN to rebuild it.
image_available_locally() {
  local tag="$1"
  docker image inspect "${tag}" >/dev/null 2>&1
}

# ── import into k3d ───────────────────────────────────────────────────────────

import_image() {
  local tag="$1"
  step "Importing ${tag} → k3d cluster '${CLUSTER}'"
  # k3d-runner sees the host Docker daemon via the mounted socket, so it can
  # find the locally built image and stream it into the cluster's containerd.
  #
  # k3d exits 0 even when the per-node import failed — it logs the node error
  # and still prints "Successfully imported image(s)". Left unchecked that turns
  # a failed import into a green run, and the first agent pod to schedule fails
  # with an opaque "Failed to pull the agent image" instead. So verify, and
  # retry once: the failure mode we have seen is the tools node exiting 0
  # without writing the tarball, which a second attempt clears.
  local attempt
  for attempt in 1 2; do
    ${COMPOSE} run --rm k3d-runner k3d image import "${tag}" --cluster "${CLUSTER}"
    if image_loaded_in_cluster "${tag}"; then
      green "  imported"
      return 0
    fi
    if [[ "${attempt}" == 1 ]]; then
      printf '\033[33m  %s\033[0m\n' "import reported success but ${tag} is not in the cluster — retrying"
    fi
  done
  red "Failed to import ${tag} into cluster '${CLUSTER}': k3d reported success but the image is not in the node's containerd store. Check the k3d output above for a per-node import error."
}

# ── main ──────────────────────────────────────────────────────────────────────

ensure_image() {
  local name="$1" dockerfile="$2" context="$3" tag="$4"
  if image_loaded_in_cluster "${tag}"; then
    green "${name} ${tag} already in cluster '${CLUSTER}' — skipping"
  elif image_available_locally "${tag}"; then
    green "${name} ${tag} already built locally — importing without rebuilding"
    import_image "${tag}"
  else
    build_image "${name}" "${dockerfile}" "${context}" "${tag}"
    import_image "${tag}"
  fi
}

if [[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]]; then
  ensure_image "openclaw-base" "openclaw-base/Dockerfile" "openclaw-base" "${OPENCLAW_IMAGE}"
fi

if [[ "${TARGET}" == "all" || "${TARGET}" == "hermes" ]]; then
  ensure_image "hermes-base" "hermes-base/Dockerfile" "hermes-base" "${HERMES_IMAGE}"
fi

# ── summary ───────────────────────────────────────────────────────────────────

printf '\n'
green "Images loaded into k3d cluster '${CLUSTER}'."
[[ "${TARGET}" == "all" || "${TARGET}" == "openclaw" ]] && printf "  openclaw → %s\n" "${OPENCLAW_IMAGE}"
[[ "${TARGET}" == "all" || "${TARGET}" == "hermes"   ]] && printf "  hermes   → %s\n" "${HERMES_IMAGE}"
printf '\n'
printf "Pods will use imagePullPolicy=IfNotPresent (pinned tags) and skip the registry.\n\n"
