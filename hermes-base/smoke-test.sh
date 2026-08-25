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
kwarg_at_call_site('/opt/hermes/agent/conversation_loop.py', 'post_llm_call', 'session_id=')

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
