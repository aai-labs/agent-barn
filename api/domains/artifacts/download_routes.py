"""App-facing byte proxy. Download authority remains opaque and provider-validated."""

import logging
import re
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from api.domains.artifacts.routes import Service


class DownloadAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value: object) -> object:
            if isinstance(value, str):
                return re.sub(
                    r"(/api/v1/agent-artifacts/[^?\s\"]+)\?[^\s\"]*",
                    r"\1?access=<redacted>",
                    value,
                )
            return value

        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


logging.getLogger("uvicorn.access").addFilter(DownloadAccessLogFilter())
router = APIRouter(prefix="/agent-artifacts", tags=["agent-artifacts"])


@router.get(
    "/{organization_id}/{agent_id}/{artifact_id}",
    responses={200: {"content": {"application/octet-stream": {}}}},
    response_class=StreamingResponse,
)
def download_artifact(
    organization_id: UUID,
    agent_id: UUID,
    artifact_id: UUID,
    service: Service,
    access: Annotated[str, Query(max_length=8192)] = "",
):
    download = service.download(organization_id, agent_id, artifact_id, access)
    return StreamingResponse(
        download.chunks,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(download.filename, safe=""),
            "Content-Length": str(download.size),
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
        background=BackgroundTask(download.close),
    )
