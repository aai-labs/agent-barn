#!/usr/bin/env bash
# Monitoring chart checks: promtool unit tests for the alert rules and a
# PromQL parse check for every dashboard panel expr. Requires helm, docker,
# and the chart dependency built (helm dependency build helm/monitoring).
set -euo pipefail

cd "$(dirname "$0")/../../.."
GEN=helm/monitoring/tests/generated
mkdir -p "$GEN"

PROMTOOL_IMAGE="${PROMTOOL_IMAGE:-prom/prometheus:v3.5.0}"

# --no-project --with pyyaml: the extractor only needs PyYAML, so don't
# force a full api dependency sync (matters on fresh CI runners).
# The alert rules live in the Prometheus server ConfigMap
# (serverFiles."alerting_rules.yml"); extract.py pulls them back out of the
# full render.
helm template helm/monitoring \
  | uv run --no-project --with pyyaml python helm/monitoring/tests/extract.py rules \
  > "$GEN/rules.yaml"

uv run --no-project --with pyyaml python helm/monitoring/tests/extract.py dashboards helm/monitoring/dashboards \
  > "$GEN/dashboard-rules.yaml"

docker run --rm -v "$PWD/helm/monitoring/tests:/tests:ro" \
  --entrypoint promtool "$PROMTOOL_IMAGE" \
  check rules /tests/generated/dashboard-rules.yaml

docker run --rm -v "$PWD/helm/monitoring/tests:/tests:ro" \
  --entrypoint promtool "$PROMTOOL_IMAGE" \
  test rules /tests/alerts_test.yaml

echo "monitoring checks passed"
