#!/usr/bin/env bash
# Monitoring chart checks: promtool unit tests for the alert rules and a
# PromQL parse check for every dashboard panel expr. Requires helm, docker,
# and the chart dependency built (helm dependency build helm/monitoring).
set -euo pipefail

cd "$(dirname "$0")/../../.."
GEN=helm/monitoring/tests/generated
mkdir -p "$GEN"

PROMTOOL_IMAGE="${PROMTOOL_IMAGE:-prom/prometheus:v3.5.0}"

helm template helm/monitoring \
  --show-only templates/prometheusrule.yaml \
  --set kube-prometheus-stack.grafana.adminPassword=unused \
  | (cd api && uv run python ../helm/monitoring/tests/extract.py rules) \
  > "$GEN/rules.yaml"

(cd api && uv run python ../helm/monitoring/tests/extract.py dashboards ../helm/monitoring/dashboards) \
  > "$GEN/dashboard-rules.yaml"

docker run --rm -v "$PWD/helm/monitoring/tests:/tests:ro" \
  --entrypoint promtool "$PROMTOOL_IMAGE" \
  check rules /tests/generated/dashboard-rules.yaml

docker run --rm -v "$PWD/helm/monitoring/tests:/tests:ro" \
  --entrypoint promtool "$PROMTOOL_IMAGE" \
  test rules /tests/alerts_test.yaml

echo "monitoring checks passed"
