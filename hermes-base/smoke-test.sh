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
from gateway.session import SessionEntry, SessionStore
from hermes_cli.hooks import _DEFAULT_PAYLOADS
from hermes_cli.plugins import VALID_HOOKS

hooks = {'pre_gateway_dispatch', 'post_llm_call', 'pre_tool_call', 'post_tool_call', 'on_session_end'}
assert hooks <= VALID_HOOKS, hooks - VALID_HOOKS
assert 'tool_call_id' in _DEFAULT_PAYLOADS['pre_tool_call']
assert 'tool_call_id' in _DEFAULT_PAYLOADS['post_tool_call']
assert hasattr(SessionStore, 'list_sessions')
fields = set(SessionEntry.__dataclass_fields__)
assert {'session_id', 'session_key', 'origin', 'chat_type'} <= fields, fields
"

if [ "$CLOUD_CLIS" = "true" ]; then
    check aws    aws --version
    check gcloud gcloud --version
    check az     az --version
fi

echo 'All smoke tests passed'
