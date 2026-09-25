"""Render checks for Prometheus/Alertmanager web auth.

Agent pods share the namespace with the monitoring stack, so both servers
require basic auth and every in-cluster client (probes, config reloaders,
Prometheus's self-scrape and alert delivery, Grafana) must present it.
Renders the chart with the values helmfile passes (web-auth-values.yaml) and
asserts the wiring; also checks the chart refuses inconsistent input.

Usage: python web_auth_test.py <chart dir>
"""

import base64
import subprocess
import sys

import bcrypt
import yaml

CHART = sys.argv[1]
VALUES = f"{CHART}/tests/web-auth-values.yaml"
USER = "monitoring"
PASSWORD = "s3cretPassw0rd"
MOUNT = "/etc/monitoring-web-auth"
SECRET = "monitoring-web-auth"
BASIC = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def render(*extra):
    return subprocess.run(
        ["helm", "template", "monitoring", CHART, "--namespace", "agent-farm", *extra],
        capture_output=True,
        text=True,
    )


def find(docs, kind, name):
    for d in docs:
        if d and d.get("kind") == kind and d["metadata"]["name"] == name:
            return d
    return None


def container(workload, name_part):
    for c in workload["spec"]["template"]["spec"]["containers"]:
        if name_part in c["name"]:
            return c
    return None


def mounts_secret(workload, c):
    volumes = {
        v["name"]: v.get("secret", {}).get("secretName")
        for v in workload["spec"]["template"]["spec"].get("volumes", [])
    }
    return any(
        m["mountPath"] == MOUNT and volumes.get(m["name"]) == SECRET for m in c.get("volumeMounts", [])
    )


def probe_header(probe):
    headers = (probe or {}).get("httpGet", {}).get("httpHeaders", [])
    return {h["name"]: h["value"] for h in headers}.get("Authorization")


result = render("-f", VALUES)
if result.returncode != 0:
    sys.exit(f"render with web auth values failed:\n{result.stderr}")
docs = list(yaml.safe_load_all(result.stdout))

# --- Secret: bcrypt web config for the servers, plain password for clients ---
secret = find(docs, "Secret", SECRET)
check(secret is not None, f"Secret {SECRET} is rendered")
if secret:
    data = {k: base64.b64decode(v).decode() for k, v in secret.get("data", {}).items()}
    check(data.get("password") == PASSWORD, "Secret carries the client password")
    users = (yaml.safe_load(data.get("web-config.yml", "")) or {}).get("basic_auth_users", {})
    hashed = users.get(USER, "")
    check(
        bool(hashed) and bcrypt.checkpw(PASSWORD.encode(), hashed.encode()),
        f"web-config.yml has a bcrypt hash of the password for user '{USER}'",
    )

# --- Prometheus server ---
prom = find(docs, "Deployment", "monitoring-prometheus-server")
check(prom is not None, "Prometheus server Deployment is rendered")
if prom:
    server = container(prom, "prometheus-server")
    if "configmap-reload" in server["name"]:
        server = next(c for c in prom["spec"]["template"]["spec"]["containers"] if "reload" not in c["name"])
    check(f"--web.config.file={MOUNT}/web-config.yml" in server["args"], "Prometheus runs with --web.config.file")
    check(mounts_secret(prom, server), f"Prometheus mounts {SECRET} at {MOUNT}")
    check(probe_header(server.get("readinessProbe")) == BASIC, "Prometheus readiness probe authenticates")
    check(probe_header(server.get("livenessProbe")) == BASIC, "Prometheus liveness probe authenticates")
    reload = container(prom, "configmap-reload")
    check(
        f"--reload-url=http://{USER}:{PASSWORD}@127.0.0.1:9090/-/reload" in reload["args"],
        "Prometheus config reloader authenticates",
    )

cm = find(docs, "ConfigMap", "monitoring-prometheus-server")
cfg = yaml.safe_load(cm["data"]["prometheus.yml"]) if cm else {}
want_auth = {"username": USER, "password_file": f"{MOUNT}/password"}
self_scrape = next((j for j in cfg.get("scrape_configs", []) if j["job_name"] == "prometheus"), {})
check(self_scrape.get("basic_auth") == want_auth, "Prometheus self-scrape authenticates")
am_targets = cfg.get("alerting", {}).get("alertmanagers", [])
check(
    bool(am_targets) and all(a.get("basic_auth") == want_auth for a in am_targets),
    "Prometheus authenticates to Alertmanager",
)

# --- Alertmanager ---
am = find(docs, "StatefulSet", "monitoring-alertmanager")
check(am is not None, "Alertmanager StatefulSet is rendered")
if am:
    server = container(am, "alertmanager")
    if "reload" in server["name"]:
        server = next(c for c in am["spec"]["template"]["spec"]["containers"] if "reload" not in c["name"])
    check(f"--web.config.file={MOUNT}/web-config.yml" in server["args"], "Alertmanager runs with --web.config.file")
    check(mounts_secret(am, server), f"Alertmanager mounts {SECRET} at {MOUNT}")
    check(probe_header(server.get("readinessProbe")) == BASIC, "Alertmanager readiness probe authenticates")
    check(probe_header(server.get("livenessProbe")) == BASIC, "Alertmanager liveness probe authenticates")
    # The subchart's reloader is off by default (config changes roll the pod
    # via its checksum annotation); if it's ever enabled it must authenticate.
    reload = container(am, "reload")
    check(
        reload is None or any(a.startswith(f"--reload-url=http://{USER}:{PASSWORD}@") for a in reload["args"]),
        "Alertmanager config reloader (if enabled) authenticates",
    )

# --- Grafana datasource ---
datasource = None
for d in docs:
    if d and d.get("kind") in ("ConfigMap", "Secret"):
        raw = (d.get("data") or {}).get("datasources.yaml") or (d.get("stringData") or {}).get("datasources.yaml")
        if raw and d.get("kind") == "Secret" and "data" in d:
            raw = base64.b64decode(raw).decode()
        if raw:
            datasource = next(s for s in yaml.safe_load(raw)["datasources"] if s["name"] == "Prometheus")
check(datasource is not None, "Grafana Prometheus datasource is rendered")
if datasource:
    check(datasource.get("basicAuth") is True, "Grafana datasource uses basic auth")
    check(datasource.get("basicAuthUser") == USER, "Grafana datasource user")
    check(
        (datasource.get("secureJsonData") or {}).get("basicAuthPassword") == "$MONITORING_WEB_PASSWORD",
        "Grafana datasource reads the password from its env",
    )
grafana = find(docs, "Deployment", "monitoring-grafana")
if grafana:
    env = {e["name"]: e for c in grafana["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
    ref = env.get("MONITORING_WEB_PASSWORD", {}).get("valueFrom", {}).get("secretKeyRef", {})
    check(ref == {"name": SECRET, "key": "password"}, f"Grafana gets MONITORING_WEB_PASSWORD from {SECRET}")

# --- The chart refuses input that would lock out a client ---
missing = render()
check(
    missing.returncode != 0 and "webAuth.password" in missing.stderr,
    "rendering without webAuth.password fails naming the value",
)
mismatch = render("-f", VALUES, "--set", "prometheus.server.probeHeaders[0].value=Basic d3Jvbmc=")
check(
    mismatch.returncode != 0 and "probeHeaders" in mismatch.stderr,
    "a probe header that doesn't match the password fails the render",
)

for args, needle, what in [
    (["--set", "prometheus.configmapReload.reloadUrl=http://127.0.0.1:9090/-/reload"], "reloadUrl", "an unauthenticated reloader URL"),
    (["--set", "prometheus.alertmanager.readinessProbe.httpGet.httpHeaders[0].value=Basic d3Jvbmc="], "readinessProbe", "a wrong Alertmanager probe header"),
    (["--set", "webAuth.password=not-alnum:@/"], "alphanumeric", "a password that can't go in a URL"),
]:
    bad = render("-f", VALUES, *args)
    check(bad.returncode != 0 and needle in bad.stderr, f"{what} fails the render")

if failures:
    print("web auth checks FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("web auth checks passed")
