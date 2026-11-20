"""Execute only deterministic fixture commands, as the runtime image's actual user."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

command_env = dict(os.environ)


def run(args, **kwargs):
    kwargs.setdefault("env", command_env)
    result = subprocess.run(args, check=False, capture_output=True, timeout=30, **kwargs)
    assert result.returncode == 0, result.stderr.decode()
    return result


relay = "/app/config/ssh-agent-relay.py"
relay_python = "/opt/agentbarn-ssh/bin/python"
bot_id = os.environ.get("SSH_TEST_BOT_ID")
if bot_id and sys.argv[1] == "hermes":
    shutil.copyfile("/app/config/SOUL.md", "/opt/data/SOUL.md")
    shutil.copyfile("/app/config/hermes-config.yaml", "/opt/data/config.yaml")
    run([sys.executable, "/app/config/bot-setup.py"])
    served = json.loads(Path("/run/agentbarn/env/active-bots.json").read_text())
    assert bot_id in [entry["id"] for entry in served], "Bot setup must succeed before its terminal is tested"
run([relay_python, relay, "--configure"])
process = subprocess.Popen([relay_python, relay], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    run([relay_python, relay, "--wait"])
    profile_path = f"/app/bots/{bot_id}/ssh-client.json" if bot_id else "/app/config/ssh-client.json"
    alias = json.loads(Path(profile_path).read_text())[0]["alias"]
    if bot_id:
        command_env["SSH_AUTH_SOCK"] = f"/run/agentbarn-ssh/{bot_id}/agent.sock"
        command_env["AGENTBARN_SSH_DIRECTORY"] = f"/run/agentbarn-ssh/{bot_id}"
    if sys.argv[2:] == ["--expect-refusal"]:
        result = subprocess.run(["ssh", alias, "true"], env=command_env, check=False, capture_output=True, timeout=30)
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

            scope_token = home_token = None
            if bot_id:
                from agent.secret_scope import (  # ty: ignore[unresolved-import]
                    build_profile_secret_scope,
                    reset_secret_scope,
                    set_multiplex_active,
                    set_secret_scope,
                )
                from hermes_constants import (  # ty: ignore[unresolved-import]
                    reset_hermes_home_override,
                    set_hermes_home_override,
                )

                home = Path("/opt/data/profiles") / bot_id
                set_multiplex_active(True)
                home_token = set_hermes_home_override(home)
                scope_token = set_secret_scope(build_profile_secret_scope(home))
            try:
                native = json.loads(terminal_tool(native_command, timeout=20, task_id="ssh-contract", workdir="/tmp"))
                assert native["exit_code"] == 0 and native["output"] == "native-ssh", native
            finally:
                cleanup_all_environments()
                if bot_id:
                    reset_secret_scope(scope_token)
                    reset_hermes_home_override(home_token)
        else:
            # Use the pinned runtime's real exec tool, including its environment policy.
            script = """
import {readdirSync} from 'node:fs';
import fs from 'node:fs';
const root = '/usr/local/lib/node_modules/openclaw/dist/';
const file = readdirSync(root).find(name => name.startsWith('bash-tools-') && name.endsWith('.js'));
const {r: createExecTool} = await import(root + file);
const tool = createExecTool({host: 'gateway', security: 'full', ask: 'off',
    allowBackground: false, timeoutSec: 20, notifyOnExit: false});
let params = {command: process.argv[1], workdir: '/tmp'};
if (process.env.SSH_TEST_BOT_ID) {
  const pluginPath = '/tmp/ssh-bot-plugin';
  fs.mkdirSync(pluginPath);
  for (const [source, target] of [['index.js','index.js'], ['package.json','package.json'], ['plugin.json','openclaw.plugin.json']]) {
    fs.copyFileSync('/app/config/agentbarn-bot-env-' + source, pluginPath + '/' + target);
  }
  const {o: loadPlugins} = await import(root + 'loader-DhyKX__3.js');
  const {i: initialize, t: runner} = await import(root + 'hook-runner-global-ac8FBwry.js');
  const configured = JSON.parse(fs.readFileSync('/app/config/openclaw-config-overlay.json', 'utf8'));
  const config = {plugins: {allow: ['agentbarn-bot-env'], load: {paths: [pluginPath]},
    entries: {'agentbarn-bot-env': configured.plugins.entries['agentbarn-bot-env']}}};
  initialize(loadPlugins({config, workspaceDir: '/tmp', onlyPluginIds: ['agentbarn-bot-env'], cache: false}));
  const result = await runner().runBeforeToolCall({toolName: 'exec', params}, {agentId: process.env.SSH_TEST_BOT_ID});
  params = result.params;
}
const result = await tool.execute('ssh-contract', params);
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
        mode = oct(Path(command_env["SSH_AUTH_SOCK"]).stat().st_mode & 0o777)
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
                    "bot": bool(bot_id),
                }
            )
        )
finally:
    process.terminate()
    process.wait(timeout=5)
