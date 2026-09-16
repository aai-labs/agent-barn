#!/bin/sh
set -eu
image="${1:?usage: test-message-hooks.sh IMAGE}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
docker run --rm --network none \
    -e PYTHONPATH=/messaging -e AGENTBARN_MESSAGE_SPOOL=/tmp/completions.sqlite3 \
    -v "$repo_root/api/domains/agents/scripts/messaging:/messaging:ro" \
    -v "$repo_root/api/tests/fixtures/openclaw_message_hooks_driver.mjs:/driver.mjs:ro" \
    --entrypoint node "$image" /driver.mjs
