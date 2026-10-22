import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, greater_than_or_equal_to, has_length, less_than

from api.domains.file_sync.models import (
    FileSyncChangesCreate,
    FileSyncOperationResultCreate,
    FileSyncOperationsRead,
    FileSyncUploadCompleteCreate,
)
from api.domains.file_sync.rules import SyncCategory, classify, rules_manifest

_SCRIPT = Path(__file__).parents[2] / "domains/agents/scripts/file-sync.py"
_AGENT_ID = "11111111-1111-4111-8111-111111111111"
_KEY = "pod-ingest-key"
_BASE_PATH = f"/ingest/v1/agents/{_AGENT_ID}/file-sync"


class _Ingest:
    def __init__(self):
        self.reports: list[FileSyncChangesCreate] = []
        self.completed: list[str] = []
        self.chunks: dict[str, list[tuple[str, bytes]]] = {}
        self.known: dict[str, str] = {}
        self.report_status: list[tuple[int, dict]] = []
        self.hang = False
        self.request_times: list[float] = []
        self.operations: list[dict] = []
        self.rounds = 0
        self.results: list[FileSyncOperationResultCreate] = []
        self.downloads: dict[str, tuple[int, bytes]] = {}
        self.on_download: Callable[[], None] | None = None
        self._uploads: dict[str, str] = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def upload_url(self, path: str) -> str:
        token = f"u{len(self._uploads) + 1}"
        self._uploads[token] = path
        return f"{self.url}/upload/{token}"

    def download(self, path: str, content: bytes, version: str = "v2", status: int = 200) -> None:
        name = f"d{len(self.downloads) + 1}"
        self.downloads[name] = (status, content)
        self.operations.append(
            {
                "path": path,
                "action": "download",
                "url": f"{self.url}/download/{name}",
                "expires_at": None,
                "version": version,
            }
        )

    def reupload(self, path: str) -> None:
        self.operations.append(
            {
                "path": path,
                "action": "reupload",
                "url": self.upload_url(path),
                "expires_at": "2099-01-01T00:00:00Z",
                "version": None,
            }
        )

    def _handler(self):
        ingest = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return None

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _send(self, status: int, payload: dict | None = None, headers: dict | None = None):
                body = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if ingest.hang:
                    time.sleep(30)
                if self.headers.get("Authorization") != f"Bearer {_KEY}":
                    self._send(401)
                    return
                if self.path == f"{_BASE_PATH}/changes":
                    ingest.request_times.append(time.monotonic())
                    report = FileSyncChangesCreate.model_validate_json(self._body())
                    ingest.reports.append(report)
                    if ingest.report_status:
                        status, headers = ingest.report_status.pop(0)
                        self._send(status, {"detail": "x"}, headers)
                        return
                    uploads = [
                        {"path": entry.path, "url": ingest.upload_url(entry.path), "expires_at": "2099-01-01T00:00:00Z"}
                        for entry in report.entries
                        if ingest.known.get(entry.path) != entry.sha256
                    ]
                    self._send(200, {"uploads": uploads})
                elif self.path == f"{_BASE_PATH}/uploads/complete":
                    done = FileSyncUploadCompleteCreate.model_validate_json(self._body())
                    ingest.completed.append(done.path)
                    self._send(204)
                elif self.path == f"{_BASE_PATH}/operations/result":
                    ingest.results.append(FileSyncOperationResultCreate.model_validate_json(self._body()))
                    self._send(204)
                else:
                    self._send(404)

            def do_GET(self):
                if self.path.startswith("/download/"):
                    if self.headers.get("Authorization") is not None:
                        self._send(400)
                        return
                    if ingest.on_download is not None:
                        ingest.on_download()
                    status, content = ingest.downloads[self.path.rsplit("/", 1)[-1]]
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                if self.headers.get("Authorization") != f"Bearer {_KEY}":
                    self._send(401)
                    return
                if self.path == f"{_BASE_PATH}/operations":
                    handed_out = FileSyncOperationsRead.model_validate({"operations": ingest.operations})
                    ingest.operations = []
                    self._send(200, handed_out.model_dump(mode="json"))
                    ingest.rounds += 1
                else:
                    self._send(404)

            def do_PUT(self):
                token = self.path.rsplit("/", 1)[-1]
                body = self._body()
                ingest.chunks.setdefault(ingest._uploads[token], []).append((self.headers["Content-Range"], body))
                total = int(self.headers["Content-Range"].rsplit("/", 1)[1])
                received = sum(len(chunk) for _, chunk in ingest.chunks[ingest._uploads[token]])
                self._send(202 if received < total else 201, {"id": "item"})

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _rules(tmp_path: Path, runtime: str, root: Path) -> Path:
    manifest = {**rules_manifest(runtime), "root": str(root)}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(manifest))
    return path


def _write(root: Path, rel: str, content: bytes, age_seconds: float = 60) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))


def _env(tmp_path: Path, ingest_url: str, runtime: str = "openclaw") -> dict[str, str]:
    return {
        **os.environ,
        "AGENT_ID": _AGENT_ID,
        "INGEST_URL": f"{ingest_url}/ingest/v1",
        "INGEST_API_KEY": _KEY,
        "FILE_SYNC_RULES": str(_rules(tmp_path, runtime, tmp_path / "volume")),
        "FILE_SYNC_STATE": str(tmp_path / "state.json"),
    }


def _run(tmp_path: Path, ingest_url: str, runtime: str = "openclaw", *args: str):
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--once", *args],
        env=_env(tmp_path, ingest_url, runtime),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, time.monotonic() - started


def _loop_round(tmp_path: Path, ingest: _Ingest) -> None:
    rounds = ingest.rounds
    process = subprocess.Popen([sys.executable, str(_SCRIPT), "--interval", "60"], env=_env(tmp_path, ingest.url))
    try:
        deadline = time.monotonic() + 20
        while ingest.rounds == rounds and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        process.terminate()
        process.wait(timeout=10)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def _load():
    spec = importlib.util.spec_from_file_location("file_sync_helper_test", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load file-sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_new_file_is_reported_uploaded_and_confirmed(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"hello agent")
    with _Ingest() as ingest:
        result, _ = _run(tmp_path, ingest.url)

    assert_that(result.returncode, equal_to(0))
    report = ingest.reports[0]
    assert_that(report.complete, equal_to(True))
    assert_that(
        [(entry.path, entry.size, entry.sha256) for entry in report.entries],
        equal_to([("workspace/notes.md", 11, hashlib.sha256(b"hello agent").hexdigest())]),
    )
    assert_that(ingest.chunks["workspace/notes.md"], equal_to([("bytes 0-10/11", b"hello agent")]))
    assert_that(ingest.completed, equal_to(["workspace/notes.md"]))


def test_only_files_the_rules_allow_are_reported(tmp_path):
    volume = tmp_path / "volume"
    for rel in (
        "workspace/notes.md",
        "workspace/USER.md",
        "workspace/AGENTS.md",
        "workspace/skills/jira/SKILL.md",
        "openclaw.json",
        "aai-cli/key",
        "workspace/node_modules/x/index.js",
        "workspace/.git/config",
        "_Not synced/old.md",
        "workspace/.file-sync-123.tmp",
        unicodedata.normalize("NFD", "workspace/café.md"),
    ):
        _write(volume, rel, b"x")
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url)

    assert_that(
        sorted(entry.path for entry in ingest.reports[0].entries),
        equal_to(["workspace/AGENTS.md", "workspace/USER.md", "workspace/notes.md", "workspace/skills/jira/SKILL.md"]),
    )


def test_hermes_paths_are_reported_from_the_hermes_layout(tmp_path):
    volume = tmp_path / "volume"
    for rel in ("memories/USER.md", "SOUL.md", "workspace/notes.md", "config.yaml", ".env", "sessions/a.json"):
        _write(volume, rel, b"x")
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url, "hermes")

    assert_that(
        sorted(entry.path for entry in ingest.reports[0].entries),
        equal_to(["SOUL.md", "memories/USER.md", "workspace/notes.md"]),
    )


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs extra rights on Windows")
def test_symlinks_and_files_behind_them_are_never_reported(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/real.md", b"x")
    outside = tmp_path / "outside"
    _write(outside, "secret.md", b"s")
    (volume / "workspace/link.md").symlink_to(outside / "secret.md")
    (volume / "workspace/linked-dir").symlink_to(outside, target_is_directory=True)
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url)

    assert_that([entry.path for entry in ingest.reports[0].entries], equal_to(["workspace/real.md"]))


def test_once_offers_files_written_a_moment_before_it_runs(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/AGENTS.md", b"template", age_seconds=0)
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url)

    report = ingest.reports[0]
    assert_that(report.complete, equal_to(True))
    assert_that([entry.path for entry in report.entries], equal_to(["workspace/AGENTS.md"]))
    assert_that(ingest.completed, equal_to(["workspace/AGENTS.md"]))


def test_a_file_still_being_written_is_left_out_and_the_report_marked_incomplete(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/done.md", b"done")
    _write(volume, "workspace/writing.md", b"partial", age_seconds=0)
    with _Ingest() as ingest:
        _loop_round(tmp_path, ingest)

    report = ingest.reports[0]
    assert_that(report.complete, equal_to(False))
    assert_that([entry.path for entry in report.entries], equal_to(["workspace/done.md"]))
    assert_that(ingest.completed, equal_to(["workspace/done.md"]))


def test_a_known_file_still_being_written_keeps_its_last_reported_version(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"first")
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url)
        ingest.known["workspace/notes.md"] = hashlib.sha256(b"first").hexdigest()
        _write(volume, "workspace/notes.md", b"second version", age_seconds=0)
        _loop_round(tmp_path, ingest)

    second = ingest.reports[1]
    assert_that(second.complete, equal_to(True))
    assert_that(
        [(entry.path, entry.sha256) for entry in second.entries],
        equal_to([("workspace/notes.md", hashlib.sha256(b"first").hexdigest())]),
    )


def test_a_rejected_key_stops_the_loop_quietly_without_uploading(tmp_path):
    _write(tmp_path / "volume", "workspace/notes.md", b"x")
    with _Ingest() as ingest:
        ingest.report_status.append((401, {}))
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "--interval", "1"],
            env=_env(tmp_path, ingest.url),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    assert_that(result.returncode, equal_to(0))
    assert_that(ingest.reports, has_length(1))
    assert_that((ingest.chunks, ingest.completed), equal_to(({}, [])))


def test_once_never_fails_boot_when_ingest_is_down(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"x")

    result, elapsed = _run(tmp_path, "http://127.0.0.1:9", "openclaw", "--timeout", "5")

    assert_that(result.returncode, equal_to(0))
    assert_that(elapsed, less_than(15))


def test_once_never_outlives_its_timeout_when_ingest_hangs(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"x")
    with _Ingest() as ingest:
        ingest.hang = True
        result, elapsed = _run(tmp_path, ingest.url, "openclaw", "--timeout", "3")

    assert_that(result.returncode, equal_to(0))
    assert_that(elapsed, less_than(12))


def test_the_loop_waits_as_long_as_ingest_asks_when_it_is_busy(tmp_path):
    _write(tmp_path / "volume", "workspace/notes.md", b"x")
    with _Ingest() as ingest:
        ingest.report_status.append((503, {"Retry-After": "3"}))
        process = subprocess.Popen([sys.executable, str(_SCRIPT), "--interval", "1"], env=_env(tmp_path, ingest.url))
        try:
            deadline = time.monotonic() + 20
            while len(ingest.request_times) < 2 and time.monotonic() < deadline:
                time.sleep(0.1)
        finally:
            process.terminate()
            process.wait(timeout=10)

    assert_that(ingest.request_times[1] - ingest.request_times[0], greater_than_or_equal_to(2.9))


def test_a_full_round_never_removes_or_changes_a_file_on_the_volume(tmp_path):
    volume = tmp_path / "volume"
    for rel in ("workspace/a.md", "workspace/b/c.md", "workspace/USER.md", "openclaw.json"):
        _write(volume, rel, rel.encode())
    before = _snapshot(volume)
    with _Ingest() as ingest:
        _run(tmp_path, ingest.url)
        _run(tmp_path, ingest.url)

    assert_that(_snapshot(volume), equal_to(before))


def test_an_upload_is_split_into_chunks_of_a_multiple_of_320_kib(tmp_path):
    helper = _load()
    helper.CHUNK_BYTES = 327_680
    volume = tmp_path / "volume"
    content = os.urandom(327_680 * 2 + 1000)
    _write(volume, "workspace/big.bin", content)
    sent: list[tuple[str, bytes]] = []
    helper._put = lambda url, data, content_range: sent.append((content_range, data)) or 201

    helper.upload_file(volume / "workspace/big.bin", "https://upload.example", hashlib.sha256(content).hexdigest())

    assert_that(
        [content_range for content_range, _ in sent],
        equal_to(["bytes 0-327679/656360", "bytes 327680-655359/656360", "bytes 655360-656359/656360"]),
    )
    assert_that(b"".join(data for _, data in sent), equal_to(content))
    assert_that(helper.CHUNK_BYTES % 327_680, equal_to(0))


def test_a_file_changed_after_the_report_is_not_uploaded(tmp_path):
    helper = _load()
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"changed since")
    sent: list = []
    helper._put = lambda url, data, content_range: sent.append(content_range) or 201

    uploaded = helper.upload_file(volume / "workspace/notes.md", "https://upload.example", "0" * 64)

    assert_that((uploaded, sent), equal_to((False, [])))


def test_the_default_chunk_size_is_a_multiple_of_320_kib():
    assert_that(_load().CHUNK_BYTES % 327_680, equal_to(0))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _results(ingest: _Ingest) -> list[tuple]:
    return [(result.path, result.outcome, result.version, result.sha256, result.size) for result in ingest.results]


def test_a_download_replaces_the_reported_file_and_names_what_it_wrote(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"agent text")
    with _Ingest() as ingest:
        ingest.known["workspace/notes.md"] = _sha(b"agent text")
        ingest.download("workspace/notes.md", b"person's edit", version="c2")
        result, _ = _run(tmp_path, ingest.url)

    assert_that(result.returncode, equal_to(0))
    assert_that((volume / "workspace/notes.md").read_bytes(), equal_to(b"person's edit"))
    assert_that(_results(ingest), equal_to([("workspace/notes.md", "done", "c2", _sha(b"person's edit"), 13)]))
    assert_that(sorted(_snapshot(volume)), equal_to(["workspace/notes.md"]))


def test_the_next_report_carries_the_downloaded_content_at_once(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"agent text")
    with _Ingest() as ingest:
        ingest.known["workspace/notes.md"] = _sha(b"agent text")
        ingest.download("workspace/notes.md", b"person's edit")
        _run(tmp_path, ingest.url)
        ingest.known["workspace/notes.md"] = _sha(b"person's edit")
        _run(tmp_path, ingest.url)

    assert_that(
        [(entry.path, entry.sha256) for entry in ingest.reports[1].entries],
        equal_to([("workspace/notes.md", _sha(b"person's edit"))]),
    )
    assert_that(ingest.chunks, equal_to({}))


def test_a_file_the_agent_changes_during_a_download_is_kept(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"agent text")
    with _Ingest() as ingest:
        ingest.known["workspace/notes.md"] = _sha(b"agent text")
        ingest.download("workspace/notes.md", b"person's edit")
        ingest.on_download = lambda: (volume / "workspace/notes.md").write_bytes(b"agent's newer text")
        _run(tmp_path, ingest.url)

    assert_that((volume / "workspace/notes.md").read_bytes(), equal_to(b"agent's newer text"))
    assert_that(_results(ingest), equal_to([("workspace/notes.md", "local_changed", None, None, None)]))
    assert_that(sorted(_snapshot(volume)), equal_to(["workspace/notes.md"]))


def test_a_download_for_a_file_the_pod_did_not_report_is_refused(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/other.md", b"x")
    with _Ingest() as ingest:
        ingest.known["workspace/other.md"] = _sha(b"x")
        ingest.download("workspace/gone.md", b"person's edit")
        _run(tmp_path, ingest.url)

    assert_that(_results(ingest), equal_to([("workspace/gone.md", "local_changed", None, None, None)]))
    assert_that(sorted(_snapshot(volume)), equal_to(["workspace/other.md"]))


def test_a_failed_download_leaves_the_file_alone(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"agent text")
    with _Ingest() as ingest:
        ingest.known["workspace/notes.md"] = _sha(b"agent text")
        ingest.download("workspace/notes.md", b"provider error", status=500)
        _run(tmp_path, ingest.url)

    assert_that(_results(ingest), equal_to([("workspace/notes.md", "failed", None, None, None)]))
    assert_that(_snapshot(volume), equal_to({"workspace/notes.md": b"agent text"}))


def test_a_download_without_room_on_the_volume_is_skipped(tmp_path):
    helper = _load()
    helper._free_bytes = lambda directory: 10
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"agent text")
    with _Ingest() as ingest:
        ingest.download("workspace/notes.md", b"a person's much longer edit")
        outcome = helper.download_file(
            str(volume / "workspace/notes.md"), ingest.operations[0]["url"], _sha(b"agent text")
        )

    assert_that(outcome, equal_to(("skipped_no_space", None, None)))
    assert_that(_snapshot(volume), equal_to({"workspace/notes.md": b"agent text"}))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_download_keeps_the_file_permissions(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/run.sh", b"echo agent")
    (volume / "workspace/run.sh").chmod(0o750)
    with _Ingest() as ingest:
        ingest.known["workspace/run.sh"] = _sha(b"echo agent")
        ingest.download("workspace/run.sh", b"echo person")
        _run(tmp_path, ingest.url)

    assert_that((volume / "workspace/run.sh").stat().st_mode & 0o777, equal_to(0o750))


def test_a_reupload_sends_the_agents_copy_and_confirms_it(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/AGENTS.md", b"template")
    with _Ingest() as ingest:
        ingest.known["workspace/AGENTS.md"] = _sha(b"template")
        ingest.reupload("workspace/AGENTS.md")
        _run(tmp_path, ingest.url)

    assert_that(ingest.chunks, equal_to({"workspace/AGENTS.md": [("bytes 0-7/8", b"template")]}))
    assert_that((ingest.completed, ingest.results), equal_to((["workspace/AGENTS.md"], [])))


def test_a_reupload_of_a_file_the_agent_no_longer_has_is_reported_failed(tmp_path):
    volume = tmp_path / "volume"
    _write(volume, "workspace/notes.md", b"x")
    with _Ingest() as ingest:
        ingest.known["workspace/notes.md"] = _sha(b"x")
        ingest.reupload("workspace/AGENTS.md")
        _run(tmp_path, ingest.url)

    assert_that(_results(ingest), equal_to([("workspace/AGENTS.md", "failed", None, None, None)]))
    assert_that((ingest.chunks, ingest.completed), equal_to(({}, [])))


def test_jobs_never_remove_or_change_another_file_on_the_volume(tmp_path):
    volume = tmp_path / "volume"
    for rel in ("workspace/a.md", "workspace/b/c.md", "workspace/USER.md", "openclaw.json"):
        _write(volume, rel, rel.encode())
    before = _snapshot(volume)
    with _Ingest() as ingest:
        ingest.known.update({rel: _sha(rel.encode()) for rel in before})
        ingest.download("workspace/missing.md", b"edit")
        ingest.download("workspace/a.md", b"error", status=500)
        ingest.reupload("workspace/gone.md")
        _run(tmp_path, ingest.url)

    assert_that(_snapshot(volume), equal_to(before))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_the_pod_and_the_server_classify_every_path_alike(runtime):
    helper = _load()
    rules = rules_manifest(runtime)
    paths = [
        "workspace/notes.md",
        "workspace/memory/2026-10-22.md",
        "workspace/skills/jira/SKILL.md",
        "workspace/skillsX/a.md",
        "workspace/AGENTS.md",
        "workspace/AGENTS.md/nested.md",
        "workspace/USER.md",
        "workspace/MEMORY.md",
        "memories/USER.md",
        "memories/MEMORY.md",
        "memories/other.md",
        "SOUL.md",
        "config.yaml",
        ".env",
        "openclaw.json",
        "aai-cli/key",
        "workspace/node_modules/x.js",
        "workspace/a/__pycache__/m.pyc",
        "workspace/.git/HEAD",
        "_Not synced/a.md",
        "workspace/../.env",
        "workspace//a.md",
        "workspace/./a.md",
        "/workspace/a.md",
        "workspace\\a.md",
        "workspace/a\x00.md",
        "workspace",
        "",
    ]
    for path in paths:
        assert_that(
            (path, helper.synced(path, rules)),
            equal_to((path, classify(runtime, path) != SyncCategory.NEVER)),
        )
