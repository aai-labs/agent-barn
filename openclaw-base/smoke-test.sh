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

check python3        python3 --version
check "python>=3.12" python3 -c "import sys; assert sys.version_info >= (3, 12)"
check node           node --version
check npm            npm --version
check openclaw       openclaw --version
check gog            gog --version
check git            git --version
check bash           bash --version
check jq             jq --version
check rg             rg --version
check curl           curl --version
check tini           tini -h

# Chromium is deliberately absent -- web access goes through the shared firecrawl
# service. Assert the absence so a future change cannot quietly reintroduce a
# ~1.5GB per-agent browser, and so the 1Gi memory limit stays viable (a gateway
# idles near 240MiB; launching chromium and loading two pages measured 573MiB).
check no-chromium sh -c '! command -v chromium >/dev/null 2>&1 && [ ! -d /opt/playwright ]'

# The telemetry-push plugin correlates a reply to its chat through sessionKey /
# runId, and pairs tool results through toolCallId. OpenClaw exposes hook names
# only as types, so this asserts against the shipped declarations: enough to
# catch a release that renames a hook or drops a correlation field.
check telemetry-contract sh -c '
    types="$(npm root -g)/openclaw/dist/plugin-sdk/hook-types-"*.d.ts
    for token in message_received agent_end before_tool_call after_tool_call \
                 session_end sessionKey runId toolCallId; do
        grep -q "$token" $types || exit 1
    done
'

if [ "$CLOUD_CLIS" = "true" ]; then
    check aws    aws --version
    check gcloud gcloud version
    check az     az version
fi

echo 'All smoke tests passed'
