"""Disposable real Garage boundary, using fixture-only service credentials."""

import time
from contextlib import contextmanager
from pathlib import Path

import boto3
from botocore.config import Config
from testcontainers.core.container import DockerContainer

GARAGE_IMAGE = "dxflrs/garage:v2.4.1"
ACCESS_KEY = "GK" + "a" * 32
SECRET_KEY = "b" * 64


@contextmanager
def garage_storage():
    configuration = Path(__file__).resolve().parents[1] / "fixtures/artifacts/garage.toml"
    with (
        DockerContainer(GARAGE_IMAGE)
        .with_volume_mapping(str(configuration), "/etc/garage.toml", mode="ro")
        .with_env("GARAGE_DEFAULT_ACCESS_KEY", ACCESS_KEY)
        .with_env("GARAGE_DEFAULT_SECRET_KEY", SECRET_KEY)
        .with_env("GARAGE_DEFAULT_BUCKET", "agent-artifact-test")
        .with_exposed_ports(3900)
        .with_command("/garage server --single-node --default-bucket")
    ) as container:
        endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(3900)}"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="garage",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        deadline = time.monotonic() + 45
        while True:
            try:
                client.head_bucket(Bucket="agent-artifact-test")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError(container.get_logs()) from None
                time.sleep(0.2)
        yield (
            {
                "ARTIFACT_S3_BUCKET": "agent-artifact-test",
                "ARTIFACT_S3_ENDPOINT_URL": endpoint,
                "ARTIFACT_S3_REGION": "garage",
                "ARTIFACT_S3_ACCESS_KEY": ACCESS_KEY,
                "ARTIFACT_S3_SECRET_KEY": SECRET_KEY,
            },
            client,
        )
