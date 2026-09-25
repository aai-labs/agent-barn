"""The monitoring chart's hook Job runs as agent-farm-user; check the SA's Role
grants what it needs on clusters where k8s/agent-farm-user*.yaml is the only
grant (client and public clusters via deploy.sh / deploy-public.yml). On the
shared cluster the tenant chart grants more, so a gap here only shows up
there.

Usage: python sa_permissions_test.py <repo root>
"""

import pathlib
import sys

import yaml

ROOT = pathlib.Path(sys.argv[1])
MANIFESTS = ["k8s/agent-farm-user.yaml", "k8s/agent-farm-user.staging.yaml"]
# files/litellm_metrics_key.py reads the Secret before deciding to keep or
# rewrite the key.
NEEDED = [("get", "litellm-metrics-key"), ("create", None), ("update", "litellm-metrics-key")]


def allows(rules, verb, name):
    for r in rules:
        if "" not in r.get("apiGroups", []) or "secrets" not in r.get("resources", []):
            continue
        if verb not in r.get("verbs", []):
            continue
        names = r.get("resourceNames")
        if not names or (name is not None and name in names):
            return True
    return False


failures = []
for path in MANIFESTS:
    role = next(
        d for d in yaml.safe_load_all((ROOT / path).read_text()) if d and d.get("kind") == "Role"
    )
    for verb, name in NEEDED:
        if not allows(role["rules"], verb, name):
            failures.append(f"{path}: Role doesn't allow {verb} on secrets/{name or '*'}")

if failures:
    print("SA permission checks FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("SA permission checks passed")
