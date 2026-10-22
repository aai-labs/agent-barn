from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.domains.file_sync.models import FileSyncChangesCreate
from api.domains.file_sync.service import (
    FileSyncConflict,
    FileSyncIngestService,
    FileSyncNotFound,
    FileSyncPathRefused,
    FileSyncUnauthorized,
)

file_sync_ingest_router = APIRouter(prefix="/agents", tags=["file-sync"])


@file_sync_ingest_router.post("/{agent_id}/file-sync/changes", status_code=status.HTTP_204_NO_CONTENT)
def report_file_changes(
    agent_id: UUID,
    changes: FileSyncChangesCreate,
    service: Annotated[FileSyncIngestService, Injected(FileSyncIngestService)],
    authorization: Annotated[str, Header()],
):
    try:
        service.report_changes(agent_id, authorization.removeprefix("Bearer ").strip(), changes)
    except FileSyncUnauthorized:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
    except FileSyncNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except FileSyncConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except FileSyncPathRefused as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
