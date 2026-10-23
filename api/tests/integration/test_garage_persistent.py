"""Exercise the shipped Compose/bootstrap path, including real container replacement."""

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import boto3
import httpx
import pytest
from botocore.config import Config as S3Config
from botocore.exceptions import ClientError
from hamcrest import assert_that, equal_to
from sqlmodel import Session

from api.domains.artifacts.models import Artifact
from api.domains.artifacts.service import ArtifactService
from api.scripts.provision_garage import ROOT, local_compose, read_env
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.integration.test_artifacts import CONTENT, publish, staged
from api.tests.integration.test_workflows import _GIVEN, auth, base


@pytest.mark.xdist_group("heavy_containers")
def test_persistent_compose_api_download_restart_and_purge(tmp_path):
    directory = tmp_path / "garage"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = ROOT / "api/scripts/provision_garage.py"
    command = [
        sys.executable,
        str(script),
        "up",
        "--state-dir",
        str(directory),
        "--port",
        str(port),
        "--endpoint",
        f"http://127.0.0.1:{port}",
    ]
    compose = None
    restored_compose = None
    try:
        event_start = datetime.now(UTC).isoformat()
        started = subprocess.run(command, capture_output=True, text=True, check=False)
        assert_that(started.returncode, equal_to(0), "Persistent Garage bootstrap failed")
        state = json.loads((directory / "state.json").read_text())
        compose = local_compose(directory, state)
        events = subprocess.run(
            [
                "docker",
                "events",
                "--since",
                event_start,
                "--until",
                datetime.now(UTC).isoformat(),
                "--filter",
                f"label=com.docker.compose.project={state['project']}",
                "--filter",
                "event=exec_create",
                "--format",
                "{{json .}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert_that("ImportKey" in events, equal_to(True), "The key-import exec event must be observed")
        assert_that(
            state["secret_key"] in events, equal_to(False), "The application secret must never enter exec arguments"
        )
        environment = read_env(directory / "application.env")
        key_before = environment["ARTIFACT_S3_ACCESS_KEY"]
        for name in ("state.json", "application.env", "server.env", "rpc-secret"):
            assert_that((directory / name).stat().st_mode & 0o077, equal_to(0))
        client = boto3.client(
            "s3",
            endpoint_url=environment["ARTIFACT_S3_ENDPOINT_URL"],
            region_name="garage",
            aws_access_key_id=key_before,
            aws_secret_access_key=environment["ARTIFACT_S3_SECRET_KEY"],
            config=S3Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        with pytest.raises(ClientError) as rejected:
            client.create_bucket(Bucket="unauthorized-new-bucket")
        assert_that(rejected.value.response["ResponseMetadata"]["HTTPStatusCode"], equal_to(403))
        with pytest.raises(ClientError):
            client.delete_bucket(Bucket=environment["ARTIFACT_S3_BUCKET"])
        with given([set_env_variable(environment), *_GIVEN]) as context:
            artifact = publish(context)
            path = base(context) + f"/artifacts/{artifact['id']}"
            before = context.client.get(path + "/download-link", headers=auth(context)).json()
            assert_that(httpx.get(before["url"]).content, equal_to(CONTENT))
            # Recreate the container and network, preserving only the named volumes and keys.
            subprocess.run([*compose, "down"], check=True, capture_output=True)
            restarted = subprocess.run(command, capture_output=True, check=False)
            assert_that(restarted.returncode, equal_to(0), "Persistent Garage restart failed")
            assert_that(read_env(directory / "application.env")["ARTIFACT_S3_ACCESS_KEY"], equal_to(key_before))
            assert_that(httpx.get(before["url"]).content, equal_to(CONTENT))
            backup = tmp_path / "backup"
            result = subprocess.run(
                [sys.executable, str(script), "backup", "--state-dir", str(directory), "--backup-dir", str(backup)],
                capture_output=True,
                check=False,
            )
            assert_that(result.returncode, equal_to(0), "Consistent backup failed")
            subprocess.run([*compose, "down"], check=True, capture_output=True)
            restored = tmp_path / "restored"
            restore_command = [
                sys.executable,
                str(script),
                "restore",
                "--state-dir",
                str(restored),
                "--backup-dir",
                str(backup),
            ]
            # Fail after volumes/metadata are created, then recover without manual deletion.
            (backup / "data").rename(backup / "held-data")
            failed_restore = subprocess.run(restore_command, capture_output=True, check=False)
            assert_that(failed_restore.returncode, equal_to(1))
            assert_that(restored.exists(), equal_to(False))
            (backup / "held-data").rename(backup / "data")
            result = subprocess.run(
                [sys.executable, str(script), "restore", "--state-dir", str(restored), "--backup-dir", str(backup)],
                capture_output=True,
                check=False,
            )
            assert_that(result.returncode, equal_to(0), "Restore into fresh volumes failed")
            restored_compose = local_compose(restored, json.loads((restored / "state.json").read_text()))
            result = subprocess.run(
                [sys.executable, str(script), "up", "--state-dir", str(restored)],
                env={**os.environ, "GARAGE_S3_PORT": "1", "GARAGE_PUBLIC_ENDPOINT": "http://wrong-default.invalid"},
                capture_output=True,
                check=False,
            )
            assert_that(result.returncode, equal_to(0), "Restored Garage did not start")
            assert_that(read_env(restored / "application.env")["ARTIFACT_S3_ACCESS_KEY"], equal_to(key_before))
            assert_that(httpx.get(before["url"]).content, equal_to(CONTENT))
            after = context.client.get(path + "/download-link", headers=auth(context)).json()
            assert_that(httpx.get(after["url"]).content, equal_to(CONTENT))
            assert_that(
                context.client.get(base(context) + "/artifacts", headers=auth(context)).json()["total"], equal_to(1)
            )
            assert_that(context.client.delete(path, headers=auth(context)).status_code, equal_to(204))
            assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))
            assert_that(httpx.get(after["url"]).status_code, equal_to(404))
            incomplete = staged(context)
            with Session(context.postgres_delegate.engine) as session:
                row = session.get_one(Artifact, UUID(incomplete["id"]))
                row.expires_at = datetime.now(UTC) - timedelta(hours=2)
                session.add(row)
                session.commit()
            assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.get_one(Artifact, UUID(incomplete["id"])).state, equal_to("DELETED"))
        # Losing initialized volumes must never create an empty replacement store.
        subprocess.run([*restored_compose, "down", "--volumes"], capture_output=True, check=True)
        refused = subprocess.run(
            [sys.executable, str(script), "up", "--state-dir", str(restored)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert_that(refused.returncode, equal_to(1))
        assert_that("volumes are missing" in refused.stderr, equal_to(True))
        volumes = subprocess.run(
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={json.loads((restored / 'state.json').read_text())['project']}",
                "-q",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert_that(volumes.stdout.strip(), equal_to(""))
    finally:
        if compose is None and (directory / "state.json").exists():
            compose = local_compose(directory, json.loads((directory / "state.json").read_text()))
        if restored_compose is not None:
            subprocess.run([*restored_compose, "down", "--volumes"], capture_output=True, check=False)
        if compose is not None:
            subprocess.run([*compose, "down", "--volumes"], capture_output=True, check=False)


@pytest.mark.xdist_group("heavy_containers")
@pytest.mark.parametrize("explicit_endpoint", [False, True])
def test_failed_first_start_can_retry_with_another_port(tmp_path, explicit_endpoint):
    directory = tmp_path / "first-start"
    # Exercise the shipped script/config while isolating the developer's .env defaults.
    project = tmp_path / "project"
    shutil.copytree(ROOT / "docker/garage", project / "docker/garage")
    script = project / "api/scripts/provision_garage.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "api/scripts/provision_garage.py", script)
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"GARAGE_S3_PORT", "GARAGE_PUBLIC_ENDPOINT", "GARAGE_STATE_DIR"}
    }
    compose = None
    try:
        with socket.socket() as occupied:
            occupied.bind(("0.0.0.0", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            command = [sys.executable, str(script), "up", "--state-dir", str(directory)]
            failed = subprocess.run(
                [
                    *command,
                    "--port",
                    str(port),
                    *(["--endpoint", f"http://127.0.0.1:{port}"] if explicit_endpoint else []),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert_that(failed.returncode, equal_to(1))
        state = json.loads((directory / "state.json").read_text())
        compose = local_compose(directory, state)
        assert_that(state["initialized"], equal_to(False))
        volumes = subprocess.run(
            ["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={state['project']}", "-q"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert_that(volumes.stdout.strip(), equal_to(""))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            replacement_port = listener.getsockname()[1]
        retry = subprocess.run(
            [
                *command,
                "--port",
                str(replacement_port),
                *(["--endpoint", f"http://127.0.0.1:{replacement_port}"] if explicit_endpoint else []),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert_that(retry.returncode, equal_to(0), retry.stderr)
        final = json.loads((directory / "state.json").read_text())
        assert_that(final["initialized"], equal_to(True))
        assert_that(final["port"], equal_to(replacement_port))
        assert_that(urlsplit(final["endpoint"]).port, equal_to(replacement_port))
        assert_that(read_env(directory / "application.env")["ARTIFACT_S3_ENDPOINT_URL"], equal_to(final["endpoint"]))
        assert_that(final["access_key"], equal_to(state["access_key"]))
    finally:
        if compose is not None:
            subprocess.run([*compose, "down", "--volumes"], capture_output=True, check=False)
