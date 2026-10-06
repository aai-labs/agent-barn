"""Exercise startup sanitation using each pinned runtime's Python/config consumer."""

import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

runtime = sys.argv[1]
root = Path(tempfile.mkdtemp(prefix="messaging-retirement-"))
for kind in ("fresh", "upgraded", "restored"):
    state = root / kind / ".openclaw" if runtime == "openclaw" else root / kind
    state.mkdir(parents=True)
    plugins = state / ("local-plugins" if runtime == "openclaw" else "plugins")
    old = plugins / "agentbarn-messaging"
    native = state / "npm/projects/recorded/node_modules/@openclaw/slack/package.json"
    jobs = state / "cron/jobs.json"
    if runtime == "openclaw":
        (state / "openclaw.json").write_text(
            json.dumps(
                {
                    "tools": (
                        {
                            "deny": ["message", "exec"],
                            "message": {
                                "actions": {"allow": ["send"]},
                                "crossContext": {"allowAcrossProviders": False},
                            },
                        }
                        if kind != "fresh"
                        else {}
                    ),
                    "plugins": {
                        "entries": {"agentbarn-messaging": {"enabled": True}},
                        "installs": {"slack": {"version": "native"}, "agentbarn-messaging": {}},
                        "allow": ["agentbarn-messaging"],
                        "load": {"paths": [str(old)]},
                    },
                }
            )
        )
    if kind != "fresh":
        old.mkdir(parents=True)
        (old / "obsolete.py").write_text("retired")
        native.parent.mkdir(parents=True)
        native.write_text("native package and installation record")
        jobs.parent.mkdir(parents=True)
        jobs.write_text(
            json.dumps(
                {"jobs": [{"id": "legacy", "origin": {"platform": "api_server"}, "delivery": {"channel": "last"}}]}
            )
        )
        (state / "agentbarn-messages.sqlite3").write_text("private queued content")
        if kind == "restored":
            archive = root / "legacy.tar"
            with tarfile.open(archive, "w") as tar:
                tar.add(state, arcname=".")
            with tarfile.open(archive) as tar:
                tar.extractall(state, filter="data")
    before_jobs = jobs.read_bytes() if jobs.exists() else None
    for _ in range(2):
        subprocess.run(["python3", "/scripts/retire-messaging.py", runtime, str(state)], check=True)
    assert not old.exists()
    if before_jobs is not None:
        assert jobs.read_bytes() == before_jobs
        assert native.read_text() == "native package and installation record"
        assert (state / "agentbarn-messages.sqlite3").read_text() == "private queued content"
    if runtime == "openclaw":
        source = (
            Path("/scripts/openclaw/init-openclaw.js")
            .read_text()
            .replace("const HOME = process.env.HOME || '/home/node';", f"const HOME = {json.dumps(str(state.parent))};")
        )
        script = root / "init-openclaw.js"
        script.write_text(source)
        subprocess.run(["node", str(script)], check=True)
        merged = (state / "openclaw.json").read_text()
        assert "agentbarn-messaging" not in merged
        assert json.loads(merged)["plugins"]["installs"]["slack"] == {"version": "native"}
        subprocess.run(["node", "/message-tool-driver.mjs", str(state / "openclaw.json")], check=True)
        if kind != "fresh":
            assert json.loads(merged)["tools"]["deny"] == ["exec"]
            assert json.loads(merged)["tools"]["message"]["crossContext"] == {"allowAcrossProviders": False}
            assert json.loads(merged)["tools"]["message"]["actions"] == {"allow": ["send"]}
    else:
        target = state / "config.yaml"
        target.write_text(
            "plugins:\n  enabled: [telemetry-push, agentbarn-messaging]\ncommand_allowlist: [saved-grant]\n"
        )
        subprocess.run(
            ["python3", "/scripts/hermes/config-merge.py", "/app/config/hermes-config.yaml", str(target)], check=True
        )
        assert "agentbarn-messaging" not in target.read_text()
        assert "saved-grant" in target.read_text()
print(f"{runtime} fresh/upgraded/restored startup retirement and native state preservation passed")
