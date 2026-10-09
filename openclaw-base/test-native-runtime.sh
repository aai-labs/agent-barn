#!/bin/sh
set -eu
image="${1:?usage: test-native-runtime.sh IMAGE}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
docker run --rm --network none \
    -v "$repo_root/api/tests/fixtures/openclaw_native_delivery_driver.mjs:/native-driver.mjs:ro" \
    --entrypoint node "$image" /native-driver.mjs
docker run --rm --network none \
    -v "$repo_root/api/domains/agents/scripts/openclaw/plugins/agentbarn-observer:/observer:ro" \
    -v "$repo_root/api/tests/fixtures/openclaw_observer_driver.mjs:/observer-driver.mjs:ro" \
    --entrypoint node "$image" /observer-driver.mjs

sh "$repo_root/api/tests/fixtures/test-messaging-retirement.sh" "$image" openclaw
