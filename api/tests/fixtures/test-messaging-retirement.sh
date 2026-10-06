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
from api.domains.agents.builders.openclaw import build_openclaw_gateway_config, native_telegram_channel
kind, target = sys.argv[1], Path(sys.argv[2])
if kind == "hermes":
    (target / "hermes-config.yaml").write_text(yaml.safe_dump(build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")))
else:
    config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000", {
        "telegram": native_telegram_channel({"allowed_chat_ids": ["-1009", "-1010"]}),
    })
    (target / "openclaw-config-overlay.json").write_text(json.dumps(config))
PY
)
chmod -R a+rX "$work"
docker run --rm --network none \
    -v "$work:/app/config:ro" \
    -v "$repo_root/api/domains/agents/scripts:/scripts:ro" \
    -v "$fixture_dir/runtime_messaging_retirement_driver.py:/retirement-driver.py:ro" \
    -v "$fixture_dir/openclaw_message_tool_driver.mjs:/message-tool-driver.mjs:ro" \
    --entrypoint python3 "$image" /retirement-driver.py "$runtime"
