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
check git            git --version
check bash           bash --version
check jq             jq --version
check rg             rg --version
check curl           curl --version
check tini           tini -h

check chromium python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto('data:text/html,ok')
    b.close()
"

if command -v aws    >/dev/null 2>&1; then check aws    aws --version;  fi
if command -v gcloud >/dev/null 2>&1; then check gcloud gcloud version; fi
if command -v az     >/dev/null 2>&1; then check az     az version;     fi

echo 'All smoke tests passed'
