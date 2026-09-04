#!/bin/sh
set -eu

image="${1:?usage: test-image.sh IMAGE}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(dirname -- "$script_dir")"

docker run --rm \
    -v "$script_dir/smoke-test.sh:/smoke-test.sh:ro" \
    "$image" \
    /bin/sh /smoke-test.sh

(
    cd "$repo_root/api"
    uv run --frozen python tests/fixtures/hermes_pvc_permissions_driver.py "$image"
)

# Run telemetry-push against Hermes' real SessionStore. Unit-test fakes cannot
# prove that the pinned runtime still exposes the fields and hooks it consumes.
docker run --rm \
    -e AGENT_ID=00000000-0000-0000-0000-000000000000 \
    -e INGEST_URL=http://127.0.0.1:9/ingest/v1 \
    -e INGEST_API_KEY=ci \
    -v "$repo_root/api/domains/agents/scripts/hermes/plugins/telemetry-push:/plugin:ro" \
    -v "$repo_root/api/tests/fixtures/hermes_session_store_driver.py:/driver.py:ro" \
    --entrypoint python3 \
    "$image" \
    /driver.py

echo 'All Hermes image tests passed'
