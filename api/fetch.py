import sys
from kubernetes import client, config
from api.core.config import get_config

cfg = get_config()
if cfg.k8s_kubeconfig_path:
    import os

    path = os.path.abspath(cfg.k8s_kubeconfig_path)
    config.load_kube_config(config_file=path)
else:
    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()

v1 = client.CoreV1Api()
pods = v1.list_namespaced_pod(
    namespace="agent-farm",
    label_selector="app=agent-019f88e5-c647-74dc-93d0-532edea069d6",
)
if not pods.items:
    print("No pod found")
    sys.exit(0)
for pod in pods.items:
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod.metadata.name, namespace="agent-farm"
        )
        print("Logs for", pod.metadata.name)
        print(logs[-2000:])
    except Exception as e:
        print("Error fetching logs:", e)
