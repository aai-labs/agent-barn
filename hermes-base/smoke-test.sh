#!/bin/sh
set -e

check() {
    printf 'checking %s ... ' "$1"
    shift
    if ! "$@" >/dev/null 2>&1; then
        echo FAILED
        exit 1
    fi
    echo ok
}

check python3   python3 --version
check hermes    hermes --version
check aai-cli   aai-cli --help
check gog       gog --version
check jq        jq --version
check rg        rg --version
check fd        fd --version
check tini      tini -h
check ffmpeg    ffmpeg -version
check convert   convert --version
check pdftotext pdftotext -v
check sqlite3   sqlite3 --version

# Agent Barn relies on scheduled Hermes runs receiving the same durable
# MEMORY.md / USER.md stores as interactive runs. This was disabled upstream
# before v2026.8.19, so pin the runtime contract in the image smoke test rather
# than discovering a regression from a live agent's output.
check cron-memory-contract python3 -c "
import ast
import inspect

from cron import scheduler


def fail(message):
    raise SystemExit('cron memory contract broken: ' + message)


tree = ast.parse(inspect.getsource(scheduler.run_job))
agent_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and (
        (isinstance(node.func, ast.Name) and node.func.id == 'AIAgent')
        or (isinstance(node.func, ast.Attribute) and node.func.attr == 'AIAgent')
    )
]
if len(agent_calls) != 1:
    fail(f'expected one AIAgent construction in run_job, found {len(agent_calls)}')

skip_memory = next(
    (keyword.value for keyword in agent_calls[0].keywords if keyword.arg == 'skip_memory'),
    None,
)
if not isinstance(skip_memory, ast.Constant) or skip_memory.value is not False:
    fail('run_job no longer constructs its AIAgent with skip_memory=False')

disabled = scheduler._resolve_cron_disabled_toolsets({})
if 'memory' in disabled:
    fail('cron disabled toolsets still contain memory')

if not scheduler._is_cron_silence_response('[SILENT]'):
    fail('[SILENT] no longer suppresses cron delivery')
if scheduler._is_cron_silence_response('Nothing to flag today.'):
    fail('ordinary prose is incorrectly treated as cron silence')
"

check memory-prompt-contract python3 -c "
import os
import tempfile
from pathlib import Path


with tempfile.TemporaryDirectory() as temp_home:
    os.environ['HERMES_HOME'] = temp_home

    from tools.memory_tool import MemoryStore

    memories = Path(temp_home) / 'memories'
    memories.mkdir()
    memories.joinpath('MEMORY.md').write_text('scheduled-memory-sentinel', encoding='utf-8')
    memories.joinpath('USER.md').write_text('scheduled-user-sentinel', encoding='utf-8')

    store = MemoryStore(memory_enabled=True, user_profile_enabled=True)
    store.load_from_disk()
    memory_prompt = store.format_for_system_prompt('memory') or ''
    user_prompt = store.format_for_system_prompt('user') or ''

    if 'scheduled-memory-sentinel' not in memory_prompt:
        raise SystemExit('MEMORY.md content was not rendered into the system prompt')
    if 'scheduled-user-sentinel' not in user_prompt:
        raise SystemExit('USER.md content was not rendered into the system prompt')
"

check chromium python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto('data:text/html,ok')
    b.close()
"

# The telemetry-push plugin resolves a reply's chat through the gateway's
# session store. A Hermes upgrade that drops one of these has to fail here,
# on the version bump, rather than silently mis-filing conversations.
check telemetry-contract python3 -c "
import sys
sys.path.insert(0, '/opt/hermes')
from gateway.session import SessionEntry, SessionSource, SessionStore
from hermes_cli.hooks import _DEFAULT_PAYLOADS
from hermes_cli.plugins import VALID_HOOKS


def fail(message):
    raise SystemExit('telemetry-push contract broken: ' + message)


def kwarg_at_call_site(path, hook, kwarg):
    source = open(path).read()
    start = source.find('\\\"' + hook + '\\\",')
    if start == -1:
        fail(hook + ' is no longer invoked in ' + path)
    if kwarg not in source[start:start + 500]:
        fail(hook + ' no longer receives ' + kwarg)


hooks = {'pre_gateway_dispatch', 'post_llm_call', 'pre_tool_call', 'post_tool_call', 'on_session_end'}
if not hooks <= VALID_HOOKS:
    fail('missing hooks ' + str(hooks - VALID_HOOKS))

# The kwargs the chat-resolution path depends on, asserted at the real call
# sites rather than against hooks-test fixtures: pre_gateway_dispatch has no
# _DEFAULT_PAYLOADS entry, and a fixture could drift from the gateway anyway.
kwarg_at_call_site('/opt/hermes/gateway/run.py', 'pre_gateway_dispatch', 'session_store=')
kwarg_at_call_site('/opt/hermes/agent/turn_finalizer.py', 'post_llm_call', 'session_id=')

for hook in ('pre_tool_call', 'post_tool_call'):
    if 'tool_call_id' not in _DEFAULT_PAYLOADS[hook]:
        fail(hook + ' no longer carries tool_call_id')
if 'session_id' not in _DEFAULT_PAYLOADS['post_llm_call']:
    fail('post_llm_call no longer carries session_id')

if not hasattr(SessionStore, 'list_sessions'):
    fail('SessionStore.list_sessions is gone')
# Exactly what _resolve_chat reads off an entry, and off entry.origin.
if not {'session_id', 'chat_type', 'origin'} <= set(SessionEntry.__dataclass_fields__):
    fail('SessionEntry no longer exposes session_id/chat_type/origin')
if not {'chat_id', 'thread_id'} <= set(SessionSource.__dataclass_fields__):
    fail('SessionSource no longer exposes chat_id/thread_id')
"

if [ "$CLOUD_CLIS" = "true" ]; then
    check aws    aws --version
    check gcloud gcloud --version
    check az     az --version
fi

echo 'All smoke tests passed'
