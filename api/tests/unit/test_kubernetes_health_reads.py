"""Health reads must return when the API server accepts a connection but stalls."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import MagicMock

import pytest
from kubernetes import client
from urllib3.exceptions import MaxRetryError

from api.infrastructure.kubernetes.client import KubernetesClient


@pytest.mark.parametrize("method", ["list_deployments", "list_pvcs"])
def test_health_reads_time_out_on_a_stalled_api_server(method):
    release = Event()

    class StalledAPI(BaseHTTPRequestHandler):
        def do_GET(self):
            release.wait(12)
            body = json.dumps({"apiVersion": "v1", "kind": "List", "items": []}).encode()
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), StalledAPI)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    configuration = client.Configuration()
    configuration.host = f"http://127.0.0.1:{server.server_port}"
    configuration.retries = 0
    k8s = KubernetesClient(config=MagicMock())
    try:
        with client.ApiClient(configuration) as transport:
            k8s._core_v1 = client.CoreV1Api(transport)
            k8s._apps_v1 = client.AppsV1Api(transport)
            with pytest.raises(MaxRetryError, match="Read timed out"):
                getattr(k8s, method)("health-test")
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()
