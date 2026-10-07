#!/bin/sh
set -eu
image="${1:?usage: test-healthz-metrics.sh IMAGE}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(dirname -- "$script_dir")"

# The healthz server reports the container's own CPU and memory from its cgroup v2
# files. Run the real script under known limits, as the image's own user, and check
# the numbers: unit tests use a fake directory and cannot prove the files are there
# or readable to this user. The same check for Hermes lives in hermes-base/test-image.sh.
docker run --rm --network none --memory 1g --cpus 0.5 \
    -v "$repo_root/api/domains/agents/scripts/openclaw/healthz-server.js:/healthz-server.js:ro" \
    -v "$repo_root/api/tests/fixtures/openclaw_healthz_metrics_driver.mjs:/driver.mjs:ro" \
    --entrypoint node \
    "$image" \
    /driver.mjs /healthz-server.js

echo 'OpenClaw healthz metrics test passed'
