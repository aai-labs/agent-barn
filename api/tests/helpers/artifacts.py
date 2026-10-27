"""Disposable Garage, with control-plane authority kept out of application config."""

import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from sqlmodel import Session, select
from testcontainers.core.container import DockerContainer

from api.core.config import Config
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.models import ArtifactBucket
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
        buckets = context.injector.get(ArtifactBucketRepository)
        with Session(context.postgres_delegate.engine) as session:
            existing = session.exec(select(ArtifactBucket).where(ArtifactBucket.agent_id == context.agent.id)).first()
        if existing is None:
            row = buckets.reserve(context.agent.id, context.agent.organization_id)
            ArtifactBucketProvisioner(buckets, config, provider).process(row.id)


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


@contextmanager
def running_product_api(context):
    """Real HTTP boundary, including response emission before background work."""
    import socket
    from threading import Thread

    import uvicorn

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(context.client.app, log_level="error", lifespan="off"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Product HTTP server did not start")
                time.sleep(0.01)
            yield origin
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Product HTTP server did not stop")


@contextmanager
def cleanup_snapshot_barrier(engine):
    """Hold cleanup after its statement snapshot, before its artifact row lock.

    The always-true SQL predicate only schedules the real query; eligibility and
    production lifecycle code are unchanged. Observe PostgreSQL's wait event so
    the test does not infer snapshot timing from a Python-side sleep.
    """
    from threading import Event

    from sqlalchemy import event, text

    scanning = Event()

    def delay_selection(connection, cursor, statement, parameters, execution_context, executemany):
        if "FOR UPDATE OF artifact SKIP LOCKED" in statement:
            assert "ORDER BY artifact.expires_at" in statement
            statement = statement.replace(
                "ORDER BY artifact.expires_at",
                "AND (SELECT true FROM pg_sleep(3)) /* AF415_PIN_RACE */ ORDER BY artifact.expires_at",
            )
            scanning.set()
        return statement, parameters

    def wait_for_snapshot():
        assert scanning.wait(timeout=5), "Cleanup selection did not start"
        deadline = time.monotonic() + 2
        while True:
            with engine.connect() as connection:
                sleeping = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event = 'PgSleep' AND query LIKE '%AF415_PIN_RACE%'"
                    )
                ).scalar_one()
            if sleeping:
                return
            assert time.monotonic() < deadline, "Cleanup did not reach its database scheduling barrier"
            time.sleep(0.01)

    event.listen(engine, "before_cursor_execute", delay_selection, retval=True)
    try:
        yield wait_for_snapshot
    finally:
        event.remove(engine, "before_cursor_execute", delay_selection)
