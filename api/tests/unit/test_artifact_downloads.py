import asyncio
import logging
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, is_

from api.core.config import Config
from api.domains.artifacts.download_routes import DownloadAccessLogFilter, download_artifact
from api.domains.artifacts.models import Artifact
from api.domains.artifacts.storage import ArtifactDownload
from api.infrastructure.s3.client import ArtifactStorage


@pytest.mark.parametrize("query", ["access=private-value", "%61ccess=private-value", "foo=x&access=private-value"])
def test_download_access_log_redacts_bearer_without_breaking_uvicorn_format(query):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/api/v1/agent-artifacts/org/agent/file?" + query, "1.1", 200),
        None,
    )
    DownloadAccessLogFilter().filter(record)
    assert_that("private-value" in record.getMessage(), is_(False))
    assert_that("access=<redacted>" in record.getMessage(), is_(True))


def test_asgi_disconnect_closes_upstream_without_caller_invoking_close():
    closed = []
    sent = []

    def chunks():
        while True:
            yield b"chunk"

    service = Mock()
    service.download.return_value = ArtifactDownload("file.csv", 100, chunks(), lambda: closed.append(True))
    response = download_artifact(uuid4(), uuid4(), uuid4(), service, "opaque-provider-authority")

    async def exercise_disconnect():
        first_chunk = asyncio.Event()

        async def receive():
            await first_chunk.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                sent.append(message)
                first_chunk.set()
                await asyncio.sleep(0)

        # Uvicorn advertises ASGI HTTP 2.3: StreamingResponse observes disconnect
        # through receive() and must run upstream cleanup without an explicit close.
        await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), timeout=5)

    asyncio.run(exercise_disconnect())
    assert_that(bool(sent), is_(True))
    assert_that(all(message["more_body"] for message in sent), is_(True))
    assert_that(closed, equal_to([True]))


@pytest.mark.parametrize("finish", [True, False])
def test_stream_reads_in_bounded_chunks_and_closes_on_completion_or_disconnect(monkeypatch, finish):
    content = b"x" * (128 * 1024 + 5)
    stream = BytesIO(content)
    response = Mock(status=200, headers={"Content-Length": str(len(content))}, read=stream.read, close=stream.close)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr("api.infrastructure.s3.client.build_opener", lambda *args: opener)
    storage = ArtifactStorage(Mock(spec=Config), Mock())
    client = Mock()
    client.generate_presigned_url.return_value = "http://private-store/bucket/key?unused=authority"
    monkeypatch.setattr(storage, "client", lambda artifact: client)
    artifact = Mock(spec=Artifact, bucket="bucket", object_key="key", filename="file.csv", size=len(content))
    download = storage.download(artifact, "eD15")  # opaque transport of fixture query x=y
    first = next(download.chunks)
    assert_that(len(first), equal_to(64 * 1024))
    if finish:
        assert_that(first + b"".join(download.chunks), equal_to(content))
    download.close()
    assert_that(stream.closed, is_(True))


@pytest.mark.parametrize("query", ["x=bad value", "x=bad\x01value"])
def test_malformed_signed_query_is_denied(monkeypatch, query):
    import base64

    from api.domains.artifacts.storage import DownloadDenied

    storage = ArtifactStorage(Mock(spec=Config), Mock())
    client = Mock()
    monkeypatch.setattr(storage, "client", lambda artifact: client)
    access = base64.urlsafe_b64encode(query.encode()).decode()
    with pytest.raises(DownloadDenied):
        storage.download(Mock(spec=Artifact), access)
    client.generate_presigned_url.assert_not_called()
