import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries

SCRIPT = Path(__file__).parents[2] / "domains/agents/scripts/agentbarn_task.py"
AGENT_ID = "0199f1d2-0000-7000-8000-000000000001"
TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"
ARTIFACT_ID = "0199f1d2-0000-7000-8000-0000000000bb"


class _IngestStub:
    """Records each request and answers with a fixed status and JSON body, or one per method.

    It also serves the Artifact runtime routes under `/artifacts-runtime`, answering a
    publish as a ready Artifact unless `artifacts` says otherwise.
    """

    def __init__(
        self,
        status: int = 200,
        body: object = None,
        by_method: dict[str, tuple[int, object]] | None = None,
        artifacts: tuple[int, object] | None = None,
    ):
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                stub.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers["Authorization"],
                        "content_type": self.headers["Content-Type"],
                        "body": self.rfile.read(length),
                    }
                )
                if self.path.startswith("/artifacts-runtime/"):
                    answer_status, answer = artifacts or (200, {"id": ARTIFACT_ID, "state": "READY"})
                else:
                    answer_status, answer = (by_method or {}).get(self.command, (status, body))
                payload = json.dumps(answer if answer is not None else {"id": TASK_ID}).encode()
                self.send_response(answer_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/ingest/v1"

    @property
    def artifact_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/artifacts-runtime"


def _run(
    stub: _IngestStub | None, *args: str, stdin: str = "", cwd: Path | None = None, **env: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        cwd=cwd,
        env={
            **os.environ,
            "AGENT_ID": AGENT_ID,
            "INGEST_URL": stub.url if stub else "http://127.0.0.1:9/ingest/v1",
            "INGEST_API_KEY": "ingest-key",
            "ARTIFACT_URL": stub.artifact_url if stub else "http://127.0.0.1:9/artifacts-runtime",
            "ARTIFACT_API_KEY": "artifact-key",
            "ARTIFACT_MAX_BYTES": "1024",
            "ARTIFACT_UPLOAD_ROOTS": str(cwd or Path.cwd()),
            **env,
        },
    )


def _tasks_path(suffix: str = "") -> str:
    return f"/ingest/v1/agents/{AGENT_ID}/tasks{suffix}"


def test_create_sends_the_title_and_description_and_prints_the_task():
    with _IngestStub(status=201, body={"id": TASK_ID, "status": "open"}) as stub:
        result = _run(stub, "create", "--title", "Reconcile invoices", "--description", "For October")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(json.loads(result.stdout), has_entries(id=TASK_ID, status="open"))
    [request] = stub.requests
    assert_that(
        (request["method"], request["path"], request["authorization"], json.loads(request["body"])),
        equal_to(
            ("POST", _tasks_path(), "Bearer ingest-key", {"title": "Reconcile invoices", "description": "For October"})
        ),
    )


def test_status_patches_the_task():
    with _IngestStub() as stub:
        result = _run(stub, "status", TASK_ID, "in_progress")

    assert_that(result.returncode, equal_to(0), result.stderr)
    [request] = stub.requests
    assert_that(
        (request["method"], request["path"], json.loads(request["body"])),
        equal_to(("PATCH", _tasks_path(f"/{TASK_ID}"), {"status": "in_progress"})),
    )


def test_an_unknown_status_is_refused_without_a_request():
    with _IngestStub() as stub:
        result = _run(stub, "status", TASK_ID, "paused")

    assert_that((result.returncode != 0, stub.requests), equal_to((True, [])))


def test_note_sends_standard_input_as_the_body():
    with _IngestStub(status=201) as stub:
        result = _run(stub, "note", TASK_ID, stdin="Matched 40 of 42 invoices\n")

    assert_that(result.returncode, equal_to(0), result.stderr)
    [request] = stub.requests
    assert_that(
        (request["method"], request["path"], json.loads(request["body"])),
        equal_to(("POST", _tasks_path(f"/{TASK_ID}/notes"), {"body": "Matched 40 of 42 invoices"})),
    )


def test_an_empty_note_is_refused_without_a_request():
    with _IngestStub() as stub:
        result = _run(stub, "note", TASK_ID, stdin="  \n")

    assert_that((result.returncode, stub.requests), equal_to((1, [])))


def test_list_filters_by_status_and_prints_the_tasks():
    with _IngestStub(body={"items": [{"id": TASK_ID}], "total": 1, "page": 1, "page_size": 25}) as stub:
        result = _run(stub, "list", "--status", "open")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(json.loads(result.stdout), has_entries(total=1))
    assert_that(stub.requests[0]["path"], equal_to(_tasks_path("?status=open")))


def test_show_reads_one_task():
    with _IngestStub(body={"id": TASK_ID, "notes": [], "files": []}) as stub:
        result = _run(stub, "show", TASK_ID)

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that((stub.requests[0]["method"], stub.requests[0]["path"]), equal_to(("GET", _tasks_path(f"/{TASK_ID}"))))


def _attach_requests(stub: _IngestStub) -> list[tuple[str, str]]:
    return [(request["method"], request["path"]) for request in stub.requests]


def test_attach_publishes_the_file_then_attaches_its_artifact(tmp_path: Path):
    report = tmp_path / "October report.csv"
    content = b"invoice,amount\n1,10\n"
    report.write_bytes(content)

    with _IngestStub(status=201, body={"filename": "October report.csv"}) as stub:
        result = _run(stub, "attach", TASK_ID, str(report), cwd=tmp_path)

    assert_that(result.returncode, equal_to(0), result.stderr)
    create, upload, attach = stub.requests
    assert_that(
        (create["method"], create["path"], create["authorization"], json.loads(create["body"])),
        equal_to(
            (
                "POST",
                "/artifacts-runtime/artifacts",
                "Bearer artifact-key",
                {
                    "filename": "October report.csv",
                    "content_type": "text/csv",
                    "size": len(content),
                    "checksum": hashlib.sha256(content).hexdigest(),
                },
            )
        ),
    )
    assert_that(
        (upload["method"], upload["path"], upload["body"]),
        equal_to(("PUT", f"/artifacts-runtime/artifacts/{ARTIFACT_ID}/content", content)),
    )
    assert_that(
        (attach["method"], attach["path"], attach["authorization"], json.loads(attach["body"])),
        equal_to(("POST", _tasks_path(f"/{TASK_ID}/files"), "Bearer ingest-key", {"artifact_id": ARTIFACT_ID})),
    )


def test_attach_takes_an_explicit_name_and_type(tmp_path: Path):
    output = tmp_path / "out.bin"
    output.write_bytes(b"%PDF-1.7")

    with _IngestStub(status=201) as stub:
        result = _run(
            stub,
            "attach",
            TASK_ID,
            str(output),
            "--name",
            "summary.pdf",
            "--content-type",
            "application/pdf",
            cwd=tmp_path,
        )

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(
        json.loads(stub.requests[0]["body"]), has_entries(filename="summary.pdf", content_type="application/pdf")
    )


def test_attach_falls_back_to_a_generic_type(tmp_path: Path):
    output = tmp_path / "data.unknownext"
    output.write_bytes(b"data")

    with _IngestStub(status=201) as stub:
        _run(stub, "attach", TASK_ID, str(output), cwd=tmp_path)

    assert_that(json.loads(stub.requests[0]["body"])["content_type"], equal_to("application/octet-stream"))


def test_attach_refuses_a_file_over_the_limit_without_sending_it(tmp_path: Path):
    output = tmp_path / "big.csv"
    output.write_bytes(b"x" * 1025)

    with _IngestStub(status=201) as stub:
        result = _run(stub, "attach", TASK_ID, str(output), cwd=tmp_path)

    assert_that((result.returncode, stub.requests), equal_to((1, [])))
    assert_that(result.stderr, contains_string("1024-byte limit"))


def test_attach_refuses_a_missing_file(tmp_path: Path):
    with _IngestStub(status=201) as stub:
        result = _run(stub, "attach", TASK_ID, str(tmp_path / "missing.csv"), cwd=tmp_path)

    assert_that((result.returncode, stub.requests), equal_to((1, [])))


def test_attach_refuses_a_file_outside_the_workspace_without_sending_it(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secrets.env"
    outside.write_text("TOKEN=x")

    with _IngestStub(status=201) as stub:
        result = _run(stub, "attach", TASK_ID, str(outside), cwd=workspace)

    assert_that((result.returncode, stub.requests), equal_to((1, [])))
    assert_that(result.stderr, contains_string("inside your workspace"))


def test_attach_refuses_a_link_out_of_the_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secrets.env"
    outside.write_text("TOKEN=x")
    (workspace / "notes.txt").symlink_to(outside)

    with _IngestStub(status=201) as stub:
        result = _run(stub, "attach", TASK_ID, str(workspace / "notes.txt"), cwd=workspace)

    assert_that((result.returncode, stub.requests), equal_to((1, [])))


def test_attach_says_files_are_unavailable_without_file_storage(tmp_path: Path):
    report = tmp_path / "report.csv"
    report.write_bytes(b"a,b\n")

    with _IngestStub(status=201) as stub:
        result = _run(stub, "attach", TASK_ID, str(report), cwd=tmp_path, ARTIFACT_API_KEY="")

    assert_that((result.returncode, stub.requests), equal_to((1, [])))
    assert_that(result.stderr, contains_string("Files cannot be attached"))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (503, "File storage for this Agent is not available right now"),
        (413, "larger than this Agent's file limit"),
        (401, "This Agent's file credential was refused. Restart this Agent."),
    ],
)
def test_a_refused_publish_is_reported_and_nothing_is_attached(tmp_path: Path, status: int, expected: str):
    report = tmp_path / "report.csv"
    report.write_bytes(b"a,b\n")

    with _IngestStub(status=201, artifacts=(status, {"detail": "internal detail"})) as stub:
        result = _run(stub, "attach", TASK_ID, str(report), cwd=tmp_path)

    assert_that(result.returncode, equal_to(1))
    assert_that(result.stderr, contains_string(expected))
    assert_that([path for _, path in _attach_requests(stub)], equal_to(["/artifacts-runtime/artifacts"]))


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (400, {"detail": "The file is larger than the space left for this Organization's Task Files."}, "space left"),
        (404, {"detail": "Task not found"}, "agentbarn-task list"),
        (401, {"detail": "Unauthorized"}, "Restart this Agent"),
        (422, {"detail": [{"msg": "Value error, The filename must be a plain name"}]}, "must be a plain name"),
        (500, {"detail": "private backend error"}, "not confirmed"),
    ],
)
def test_a_refusal_reports_a_clear_error(status, body, expected):
    with _IngestStub(status=status, body=body) as stub:
        result = _run(stub, "status", TASK_ID, "done")

    assert_that(result.returncode, equal_to(1))
    assert_that(result.stderr, contains_string(expected))
    assert_that("private backend error" in result.stdout + result.stderr, equal_to(False))


def test_an_unreachable_service_reports_the_change_as_unconfirmed():
    result = _run(None, "status", TASK_ID, "done")

    assert_that((result.returncode, "not confirmed" in result.stderr), equal_to((1, True)))


def test_a_missing_configuration_is_reported():
    result = _run(None, "list", INGEST_API_KEY="")

    assert_that((result.returncode, "not configured" in result.stderr), equal_to((1, True)))


def test_create_can_start_the_task_in_progress():
    with _IngestStub(status=201, body={"id": TASK_ID, "status": "in_progress"}) as stub:
        result = _run(stub, "create", "--title", "Reconcile invoices", "--status", "in_progress")

    assert_that(result.returncode, equal_to(0), result.stderr)
    [request] = stub.requests
    assert_that(
        (request["method"], request["path"], json.loads(request["body"])),
        equal_to(("POST", _tasks_path(), {"title": "Reconcile invoices", "status": "in_progress"})),
    )
    assert_that(json.loads(result.stdout), has_entries(status="in_progress"))


def test_remove_file_deletes_it_from_the_task():
    with _IngestStub(status=204, body="") as stub:
        result = _run(stub, "remove-file", TASK_ID, "0199f1d2-0000-7000-8000-0000000000ff")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(
        (stub.requests[0]["method"], stub.requests[0]["path"]),
        equal_to(("DELETE", _tasks_path(f"/{TASK_ID}/files/0199f1d2-0000-7000-8000-0000000000ff"))),
    )
    assert_that(json.loads(result.stdout), has_entries(removed="0199f1d2-0000-7000-8000-0000000000ff"))


def test_create_can_add_a_note_in_the_same_call():
    with _IngestStub(status=201, body={"id": TASK_ID, "status": "in_progress"}) as stub:
        result = _run(stub, "create", "--title", "Reconcile invoices", "--status", "in_progress", "--note", "Started")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(
        [(request["method"], request["path"]) for request in stub.requests],
        equal_to([("POST", _tasks_path()), ("POST", _tasks_path(f"/{TASK_ID}/notes"))]),
    )
    assert_that(json.loads(stub.requests[1]["body"]), equal_to({"body": "Started"}))
    assert_that(json.loads(result.stdout), has_entries(id=TASK_ID, status="in_progress"))


def test_status_can_add_a_note_in_the_same_call():
    with _IngestStub(status=200, body={"id": TASK_ID, "status": "failed"}) as stub:
        result = _run(stub, "status", TASK_ID, "failed", "--note", "The booking site needs a login")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(
        [(request["method"], request["path"]) for request in stub.requests],
        equal_to([("PATCH", _tasks_path(f"/{TASK_ID}")), ("POST", _tasks_path(f"/{TASK_ID}/notes"))]),
    )
    assert_that(json.loads(stub.requests[1]["body"]), equal_to({"body": "The booking site needs a login"}))
    assert_that(json.loads(result.stdout), has_entries(status="failed"))


def test_a_note_that_was_not_recorded_is_reported_after_the_status_change():
    with _IngestStub(by_method={"PATCH": (200, {"id": TASK_ID, "status": "done"}), "POST": (503, {})}) as stub:
        result = _run(stub, "status", TASK_ID, "done", "--note", "Finished")

    assert_that(result.returncode, equal_to(1))
    assert_that(result.stderr, contains_string("status was set to done but the note was not recorded"))


def test_attach_replace_removes_earlier_files_of_the_same_name(tmp_path: Path):
    upload = tmp_path / "offsite.md"
    upload.write_text("# Offsite")
    task = {
        "id": TASK_ID,
        "files": [
            {"id": "file-old", "filename": "offsite.md"},
            {"id": "file-other", "filename": "venues.csv"},
        ],
    }
    with _IngestStub(
        by_method={"GET": (200, task), "POST": (201, {"id": "file-new", "filename": "offsite.md"}), "DELETE": (204, "")}
    ) as stub:
        result = _run(stub, "attach", TASK_ID, str(upload), "--replace", cwd=tmp_path)

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(
        _attach_requests(stub),
        equal_to(
            [
                ("GET", _tasks_path(f"/{TASK_ID}")),
                ("POST", "/artifacts-runtime/artifacts"),
                ("PUT", f"/artifacts-runtime/artifacts/{ARTIFACT_ID}/content"),
                ("POST", _tasks_path(f"/{TASK_ID}/files")),
                ("DELETE", _tasks_path(f"/{TASK_ID}/files/file-old")),
            ]
        ),
    )
    assert_that(json.loads(result.stdout), has_entries(id="file-new"))


def test_attach_replace_keeps_the_earlier_file_when_the_attach_is_refused(tmp_path: Path):
    upload = tmp_path / "offsite.md"
    upload.write_text("# Offsite")
    task = {"id": TASK_ID, "files": [{"id": "file-old", "filename": "offsite.md"}]}
    with _IngestStub(by_method={"GET": (200, task), "POST": (400, {"detail": "Task is closed"})}) as stub:
        result = _run(stub, "attach", TASK_ID, str(upload), "--replace", cwd=tmp_path)

    assert_that((result.returncode, result.stderr.strip()), equal_to((1, "Task is closed")))
    assert_that([method for method, _ in _attach_requests(stub)], equal_to(["GET", "POST", "PUT", "POST"]))


def test_create_can_say_the_task_was_recorded_automatically():
    with _IngestStub(status=201, body={"id": TASK_ID, "status": "open", "origin": "automatic"}) as stub:
        result = _run(stub, "create", "--title", "Reconcile invoices", "--origin", "automatic")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(json.loads(stub.requests[0]["body"]), equal_to({"title": "Reconcile invoices", "origin": "automatic"}))


def test_list_can_ask_for_a_larger_page():
    with _IngestStub(body={"items": [], "total": 0}) as stub:
        result = _run(stub, "list", "--page-size=100")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(stub.requests[0]["path"], equal_to(_tasks_path("?page_size=100")))


def test_a_value_that_looks_like_an_option_is_taken_as_written():
    with _IngestStub(status=201) as stub:
        result = _run(stub, "create", "--title=-v", "--description=--help")

    assert_that(result.returncode, equal_to(0), result.stderr)
    assert_that(json.loads(stub.requests[0]["body"]), equal_to({"title": "-v", "description": "--help"}))
