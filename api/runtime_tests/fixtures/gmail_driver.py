"""Real aai-cli Gmail profile from generated artifacts, run with networking disabled."""

import json
import os
import subprocess
from pathlib import Path

artifacts = json.loads(Path("/contract/artifacts.json").read_text())
config_path = f"{artifacts['home']}/.config/aai-cli/config.toml"
cli = ["aai-cli", "--config", config_path]


def run(args, env):
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=15, check=False)


def error_of(result):
    assert result.returncode != 0, result.stdout + result.stderr
    return json.loads(result.stderr.strip().splitlines()[-1])


selected = artifacts["direct"]
for name, value in selected["files"].items():
    Path(f"/app/config/{name}").write_text(value)
env = {**os.environ, **selected["env"], "HOME": artifacts["home"]}
setup = run(["sh", "/app/config/aai-cli-setup.sh"], env)
assert setup.returncode == 0, setup.stdout + setup.stderr

stored = run([*cli, "secrets", "list"], env).stdout
assert "google.gmail_client_secret" in stored and "google.gmail_refresh_token" in stored, stored
validated = run([*cli, "config", "profiles", "validate", "gmail-work"], env)
assert json.loads(validated.stdout)["valid"] is True, validated.stdout + validated.stderr

listing = [*cli, "email", "messages", "list", "--limit", "1", "--profile", "gmail-work"]
wired = error_of(run(listing, env))
# Credentials resolved; the only thing missing offline is Google itself.
assert wired["operation"] == "refresh" and "oauth2.googleapis.com/token" in wired["message"], wired

removed = run([*cli, "secrets", "remove", "google.gmail_refresh_token"], env)
assert removed.returncode == 0, removed.stdout + removed.stderr
unwired = error_of(run(listing, env))
assert unwired["operation"] != "refresh" and "refresh credentials" in unwired["message"], unwired

print(json.dumps({"refresh_attempted": True, "uid": os.getuid()}))
