"""Credential isolation in the shipped application Compose configuration."""

import json
import re
import shutil
import subprocess

from hamcrest import assert_that, equal_to, is_

from api.scripts.provision_garage import ROOT


def test_compose_storage_key_is_only_available_to_api_and_purge(tmp_path):
    source = (ROOT / "compose.yml").read_text()
    shutil.copyfile(ROOT / "compose.yml", tmp_path / "compose.yml")
    required = set(re.findall(r"\$\{([A-Z0-9_]+):?\?", source))
    settings = {name: "fixture" for name in required}
    settings.update({name: str(18000 + index) for index, name in enumerate(sorted(required)) if name.endswith("_PORT")})
    settings.update(
        {
            "ARTIFACT_S3_ACCESS_KEY": "fixture-root-key",
            "ARTIFACT_S3_SECRET_KEY": "fixture-root-secret",
        }
    )
    (tmp_path / ".env").write_text("".join(f"{key}={value}\n" for key, value in settings.items()))
    (tmp_path / ".garage").mkdir()
    shutil.copytree(ROOT / "docker/garage", tmp_path / "docker/garage")
    (tmp_path / ".garage/compose.env").write_text(
        f"GARAGE_SAVED_STATE_DIR={tmp_path / '.garage'}\nGARAGE_SAVED_VOLUME_PREFIX=fixture\nGARAGE_SAVED_S3_PORT=3900\n"
    )
    with (tmp_path / ".env").open("a") as target:
        target.write((tmp_path / ".garage/compose.env").read_text())
    (tmp_path / ".garage/server.env").write_text("GARAGE_DEFAULT_ACCESS_KEY=fixture-bootstrap\n")
    (tmp_path / ".garage/application.env").write_text(
        "ARTIFACT_S3_BUCKET=fixture-files\nARTIFACT_S3_ACCESS_KEY=fixture-private-key\nARTIFACT_S3_SECRET_KEY=fixture-private-secret\n"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(tmp_path / "compose.yml"),
            "--env-file",
            str(tmp_path / ".env"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode, equal_to(0), "Compose configuration did not render")
    services = json.loads(result.stdout)["services"]
    assert_that("garage" in services, is_(True), "Garage must run without a profile")
    assert_that("artifact-purge" in services, is_(True), "Purge must run without a profile")
    assert_that(services["api"]["depends_on"]["garage"]["condition"], equal_to("service_healthy"))
    assert_that(services["artifact-purge"]["depends_on"]["garage"]["condition"], equal_to("service_healthy"))
    for name, service in services.items():
        environment = service.get("environment", {})
        if name in {"api", "artifact-purge"}:
            assert_that(environment.get("ARTIFACT_S3_ACCESS_KEY"), equal_to("fixture-private-key"), name)
        else:
            assert_that(bool(environment.get("ARTIFACT_S3_ACCESS_KEY")), is_(False), name)
            assert_that(bool(environment.get("ARTIFACT_S3_SECRET_KEY")), is_(False), name)


def test_backup_refuses_relative_and_repository_destinations(tmp_path):
    import argparse
    from pathlib import Path

    import pytest

    from api.scripts.provision_garage import local

    directory = tmp_path / "state"
    directory.mkdir()
    (directory / "state.json").write_text(json.dumps({"project": "fixture-not-a-store", "port": 3900}))
    for destination in (Path("backup"), ROOT / "backup"):
        args = argparse.Namespace(state_dir=directory, action="backup", backup_dir=destination)
        with pytest.raises(ValueError, match="absolute and outside the repository"):
            local(args)


def test_cli_reads_dotenv_defaults_and_reports_invalid_port_without_traceback(tmp_path):
    import os
    import sys

    # A copied script uses its own temporary project root, without changing the real .env.
    project = tmp_path / "project"
    scripts = project / "api/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "api/scripts/provision_garage.py", scripts / "provision_garage.py")
    (project / ".env").write_text("GARAGE_S3_PORT=not-a-number\nGARAGE_PUBLIC_ENDPOINT=http://fixture.invalid\n")
    environment = {
        name: value for name, value in os.environ.items() if name not in {"GARAGE_S3_PORT", "GARAGE_PUBLIC_ENDPOINT"}
    }
    result = subprocess.run(
        [sys.executable, str(scripts / "provision_garage.py"), "up"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode, equal_to(1))
    assert_that(result.stderr.strip(), equal_to("GARAGE_S3_PORT must be an integer"))
    assert_that("Traceback" in result.stderr, is_(False))
    # Cluster configuration uses its explicit endpoint and ignores local .env defaults;
    # validation must fail before storage or Docker is touched.
    result = subprocess.run(
        [
            sys.executable,
            str(scripts / "provision_garage.py"),
            "cluster-config",
            "--endpoint",
            "http://fixture.invalid",
            "--port",
            "3900",
            "--state-dir",
            str(tmp_path / "state"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode, equal_to(1))
    assert_that(result.stderr.strip(), equal_to("Cluster downloads require an HTTPS origin"))


def test_unpublished_port_retry_preserves_operator_endpoint(tmp_path):
    from api.scripts.provision_garage import local_setup

    state = {
        "initialized": False,
        "project": "fixture",
        "port": 3900,
        "endpoint": "https://files.example.invalid",
        "endpoint_derived": False,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    retried = local_setup(tmp_path, 3910, None)
    assert_that(retried["port"], equal_to(3910))
    assert_that(retried["endpoint"], equal_to(state["endpoint"]))


def test_bootstrap_checks_live_rpc_address_instead_of_configured_hostname(tmp_path):
    import argparse
    from unittest.mock import patch

    import pytest

    from api.scripts import provision_garage

    node_id = "a" * 64
    state = {
        "namespace": "fixture",
        "release": "garage",
        "bucket": "fixture",
        "endpoint": "https://files.example.invalid",
        "access_key": "fixture-key",
        "secret_key": "fixture-secret",
    }
    (tmp_path / "cluster.json").write_text(json.dumps(state))
    args = argparse.Namespace(state_dir=tmp_path, kubeconfig=tmp_path / "kubeconfig", capacity="10GB")

    def fake_run(command, **kwargs):
        if "statefulset" in command:
            payload = {"spec": {"replicas": 1}}
        elif "service" in command:
            payload = {"spec": {"clusterIP": "10.43.0.10"}}
        elif command[-2:] == ["node", "id"]:
            return subprocess.CompletedProcess(command, 0, node_id + "@garage-0.fixture.svc.cluster.local:3901\n", "")
        elif "GetClusterStatus" in command:
            payload = {"nodes": [{"id": node_id, "addr": advertised}]}
        elif "GetClusterLayout" in command:
            payload = {"version": 1, "roles": [{"id": node_id}]}
        else:
            payload = {}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    # Unit fake isolates the daemon response parser; real Kubernetes verification is separate.
    with patch.object(provision_garage, "run", side_effect=fake_run):
        for advertised in ("10.42.0.10:3901", None):
            with pytest.raises(RuntimeError, match="RPC address does not match"):
                provision_garage.cluster_init(args)
            assert_that((tmp_path / "application-secret.json").exists(), is_(False))
        advertised = "10.43.0.10:3901"
        provision_garage.cluster_init(args)
        generated = json.loads((tmp_path / "application-secret.json").read_text())
        assert_that(generated["stringData"]["ARTIFACT_S3_BUCKET"], equal_to("fixture"))


def test_main_compose_works_before_garage_setup(tmp_path):
    source = (ROOT / "compose.yml").read_text()
    (tmp_path / "compose.yml").write_text(source)
    shutil.copytree(ROOT / "docker/garage", tmp_path / "docker/garage")
    required = set(re.findall(r"\$\{([A-Z0-9_]+):?\?", source))
    values = {name: "fixture" for name in required}
    values.update({name: str(18000 + i) for i, name in enumerate(sorted(required)) if name.endswith("_PORT")})
    (tmp_path / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    command = ["docker", "compose", "-f", str(tmp_path / "compose.yml")]
    for args in (["config", "--quiet"], ["--dry-run", "up", "-d", "db"], ["--dry-run", "down"]):
        result = subprocess.run([*command, *args], capture_output=True, text=True, check=False)
        assert_that(result.returncode, equal_to(0), "Root Compose must work before private Garage setup: " + str(args))
    assert_that((tmp_path / ".garage").exists(), is_(False))
