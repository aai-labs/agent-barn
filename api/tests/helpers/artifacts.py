"""Disposable Garage, with control-plane authority kept out of application config."""

import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from testcontainers.core.container import DockerContainer

from api.core.config import Config
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.provisioning import ArtifactBucketProvisioner
from api.infrastructure.s3.provisioner import GarageProvisioner

GARAGE_IMAGE = "dxflrs/garage:v2.4.1"
ADMIN_TOKEN = "c" * 64  # Disposable fixture only, never a deployment credential.
_PROVIDERS: dict[str, GarageProvisioner] = {}


class ComposeGarageProvisioner(GarageProvisioner):
    """Fixture-only control plane through exec; no host-published admin port."""

    def __init__(self, compose):
        self.compose = compose

    def request(self, operation, *, method="POST", params=None, body=None):
        payload = {**(params or {}), **(body or {})}
        if "showSecretKey" in payload:
            payload["showSecretKey"] = True
        result = subprocess.run(
            [*self.compose, "exec", "-T", "garage", "/garage", "json-api", operation, "-"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            if method == "GET" and "(404)" in result.stderr:
                return None
            raise OSError(f"Garage fixture operation {operation} failed")
        return json.loads(result.stdout)


@contextmanager
def registered_compose_storage(environment, compose):
    endpoint = environment["ARTIFACT_S3_ENDPOINT_URL"]
    provider = ComposeGarageProvisioner(compose)
    _PROVIDERS[endpoint] = provider
    try:
        yield provider
    finally:
        del _PROVIDERS[endpoint]


def provision_agents(context):
    config = context.injector.get(Config)
    provider = _PROVIDERS.get(config.artifact_s3_endpoint_url)
    if provider:
        ArtifactBucketProvisioner(context.injector.get(ArtifactBucketRepository), config, provider).run()


@contextmanager
def garage_storage():
    configuration = Path(__file__).resolve().parents[1] / "fixtures/artifacts/garage.toml"
    with (
        DockerContainer(GARAGE_IMAGE)
        .with_volume_mapping(str(configuration), "/etc/garage.toml", mode="ro")
        .with_env("GARAGE_ADMIN_TOKEN", ADMIN_TOKEN)
        .with_exposed_ports(3900, 3903)
        .with_command("/garage server --single-node")
    ) as container:
        host = container.get_container_host_ip()
        endpoint = f"http://{host}:{container.get_exposed_port(3900)}"
        admin_endpoint = f"http://{host}:{container.get_exposed_port(3903)}"
        deadline = time.monotonic() + 45
        while True:
            try:
                httpx.get(admin_endpoint + "/health", trust_env=False).raise_for_status()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError(container.get_logs()) from None
                time.sleep(0.2)
        provider = GarageProvisioner(
            Config.model_construct(artifact_provisioner_url=admin_endpoint, artifact_provisioner_token=ADMIN_TOKEN)
        )
        _PROVIDERS[endpoint] = provider
        try:
            yield (
                {
                    "ARTIFACT_S3_ENDPOINT_URL": endpoint,
                    "ARTIFACT_PROVISIONER_URL": "",
                    "ARTIFACT_PROVISIONER_TOKEN": "",
                },
                provider,
            )
        finally:
            del _PROVIDERS[endpoint]
