"""Execute only deterministic fixture commands, as the runtime image's actual user."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def run(args, **kwargs):
    result = subprocess.run(args, check=False, capture_output=True, timeout=30, **kwargs)
    assert result.returncode == 0, result.stderr.decode()
    return result


relay = "/app/config/ssh-agent-relay.py"
relay_python = "/opt/agentbarn-ssh/bin/python"
run([relay_python, relay, "--configure"])
process = subprocess.Popen([relay_python, relay], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    run([relay_python, relay, "--wait"])
    alias = json.loads(Path("/app/config/ssh-client.json").read_text())[0]["alias"]
    if sys.argv[2:] == ["--expect-refusal"]:
        result = subprocess.run(["ssh", alias, "true"], check=False, capture_output=True, timeout=30)
        assert result.returncode != 0
        print(json.dumps({"refused": True}))
    else:
        # A login shell is how normal runtime terminal invocations initialize their environment.
        result = run(["bash", "-lc", f"ssh {shlex.quote(alias)} 'printf runtime-ssh'"])
        assert result.stdout == b"runtime-ssh"
        native_command = f"ssh {shlex.quote(alias)} 'printf native-ssh'"
        if sys.argv[1] == "hermes":
            # Provided by the pinned Hermes image, not the API environment.
            from tools.terminal_tool import cleanup_all_environments, terminal_tool  # ty: ignore[unresolved-import]

            try:
                native = json.loads(terminal_tool(native_command, timeout=20, task_id="ssh-contract", workdir="/tmp"))
                assert native["exit_code"] == 0 and native["output"] == "native-ssh", native
            finally:
                cleanup_all_environments()
        else:
            # Use the pinned runtime's real exec tool, including its environment policy.
            script = """
import {readdirSync} from 'node:fs';
const root = '/usr/local/lib/node_modules/openclaw/dist/';
const file = readdirSync(root).find(name => name.startsWith('bash-tools-') && name.endsWith('.js'));
const {r: createExecTool} = await import(root + file);
const tool = createExecTool({host: 'gateway', security: 'full', ask: 'off',
    allowBackground: false, timeoutSec: 20, notifyOnExit: false});
const result = await tool.execute('ssh-contract', {command: process.argv[1], workdir: '/tmp'});
console.log(JSON.stringify(result));
"""
            native = json.loads(run(["node", "--input-type=module", "-e", script, native_command]).stdout)
            assert native["details"]["exitCode"] == 0 and native["details"]["aggregated"] == "native-ssh", native
        run(["ssh", alias, "git init --bare /tmp/runtime.git >/dev/null"])
        run(["git", "clone", f"{alias}:/tmp/runtime.git", "/tmp/clone"])
        run(["git", "-C", "/tmp/clone", "config", "user.email", "fixture@example.com"])
        run(["git", "-C", "/tmp/clone", "config", "user.name", "SSH fixture"])
        Path("/tmp/clone/report.txt").write_text("fixture file")
        run(["git", "-C", "/tmp/clone", "add", "report.txt"])
        run(["git", "-C", "/tmp/clone", "commit", "-m", "Fixture"])
        run(["git", "-C", "/tmp/clone", "push", "origin", "HEAD"])
        run(["git", "-C", "/tmp/clone", "fetch"])
        run(["scp", "/tmp/clone/report.txt", f"{alias}:/tmp/report.txt"])
        run(["sftp", "-b", "-", alias], input=b"get /tmp/report.txt /tmp/download.txt\n")
        assert Path("/tmp/download.txt").read_text() == "fixture file"
        mode = oct(Path(os.environ["SSH_AUTH_SOCK"]).stat().st_mode & 0o777)
        print(
            json.dumps(
                {
                    "ssh": True,
                    "native_terminal": True,
                    "git": True,
                    "scp": True,
                    "sftp": True,
                    "uid": os.getuid(),
                    "socket_mode": mode,
                }
            )
        )
finally:
    process.terminate()
    process.wait(timeout=5)
