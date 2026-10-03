#!/bin/sh
set -eu
image="${1:?image required}"
runtime="${2:?runtime required}"
fixture_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(cd "$fixture_dir/../../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
(cd "$repo_root/api" && PYTHONPATH="$repo_root" uv run --frozen python - "$runtime" "$work" <<'PY'
import json
import sys
from pathlib import Path
import yaml
from api.domains.agents.builders.hermes import build_hermes_gateway_config
from api.domains.agents.builders.openclaw import build_openclaw_gateway_config
kind, target = sys.argv[1], Path(sys.argv[2])
if kind == "hermes":
    (target / "hermes-config.yaml").write_text(yaml.safe_dump(build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")))
else:
    (target / "openclaw-config-overlay.json").write_text(json.dumps(build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")))
PY
)
chmod -R a+rX "$work"
docker run --rm --network none \
    -v "$work:/app/config:ro" \
    -v "$repo_root/api/domains/agents/scripts:/scripts:ro" \
    -v "$fixture_dir/runtime_messaging_retirement_driver.py:/retirement-driver.py:ro" \
    --entrypoint python3 "$image" /retirement-driver.py "$runtime"
