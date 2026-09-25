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
# The chart requires webAuth values (helmfile derives them per deploy); use
# the test fixture that mirrors them.
helm template helm/monitoring -f helm/monitoring/tests/web-auth-values.yaml \
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

# Web auth wiring (Prometheus/Alertmanager basic auth and every client).
uv run --no-project --with pyyaml --with bcrypt python helm/monitoring/tests/web_auth_test.py helm/monitoring

# The hook Job's SA grants on clusters where k8s/agent-farm-user*.yaml is all
# it gets.
uv run --no-project --with pyyaml python helm/monitoring/tests/sa_permissions_test.py .

echo "monitoring checks passed"
