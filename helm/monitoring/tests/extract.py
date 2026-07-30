"""Extract testable Prometheus artifacts from the monitoring chart.

Two modes:
  rules              read `helm template` output on stdin, print the alert
                     groups from the Prometheus server ConfigMap
                     (alerting_rules.yml) as a plain promtool rules file
  dashboards <dir>   wrap every panel expr from the dashboard JSONs as a
                     recording rule so `promtool check rules` parse-checks
                     the PromQL (Grafana variables are substituted first)

Run through the api project env for PyYAML: cd api && uv run python ...
"""

import json
import pathlib
import re
import sys

import yaml

# $__range → literal duration; ${var}/$var → permissive regex value. "$1" in
# label_replace is left alone (Grafana vars cannot start with a digit).
_RANGE_VAR = re.compile(r"\$\{?__range\}?")
_GRAFANA_VAR = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


def _rules() -> None:
    for doc in yaml.safe_load_all(sys.stdin):
        if doc and doc.get("kind") == "ConfigMap":
            raw = doc.get("data", {}).get("alerting_rules.yml")
            if raw:
                yaml.safe_dump({"groups": yaml.safe_load(raw)["groups"]}, sys.stdout, sort_keys=False)
                return
    sys.exit("no ConfigMap with alerting_rules.yml found on stdin")


def _dashboards(directory: str) -> None:
    rules = []
    for path in sorted(pathlib.Path(directory).glob("*.json")):
        dashboard = json.loads(path.read_text())
        slug = path.stem.replace("-", "_")
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                expr = target.get("expr")
                if not expr:
                    continue
                expr = _RANGE_VAR.sub("1h", expr)
                expr = _GRAFANA_VAR.sub(".+", expr)
                rules.append(
                    {
                        "record": f"dashboard_check:{slug}:panel{panel['id']}_{target.get('refId', 'a').lower()}",
                        "expr": expr,
                    }
                )
    if not rules:
        sys.exit(f"no panel exprs found under {directory}")
    yaml.safe_dump(
        {"groups": [{"name": "dashboard-exprs", "rules": rules}]},
        sys.stdout,
        sort_keys=False,
    )


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "rules":
        _rules()
    elif len(sys.argv) >= 3 and sys.argv[1] == "dashboards":
        _dashboards(sys.argv[2])
    else:
        sys.exit(__doc__)
