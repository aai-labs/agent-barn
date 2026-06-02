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

if [ "$CLOUD_CLIS" = "true" ]; then
    check aws    aws --version
    check gcloud gcloud --version
    check az     az --version
fi

echo 'All smoke tests passed'
