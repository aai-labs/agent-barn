from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.domains.file_sync.models import (
    FileSyncChangesCreate,
    FileSyncChangesRead,
    FileSyncOperationResultCreate,
    FileSyncOperationsRead,
    FileSyncUploadCompleteCreate,
)
from api.domains.file_sync.service import (
    FileSyncConflict,
    FileSyncIngestService,
    FileSyncNotFound,
    FileSyncPathRefused,
    FileSyncProviderBusy,
    FileSyncProviderFailed,
    FileSyncUnauthorized,
)

file_sync_ingest_router = APIRouter(prefix="/agents", tags=["file-sync"])


def _key(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip()


def _answer[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except FileSyncUnauthorized:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
    except FileSyncNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except FileSyncConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except FileSyncPathRefused as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except FileSyncProviderBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except FileSyncProviderFailed as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None


@file_sync_ingest_router.post("/{agent_id}/file-sync/changes", response_model=FileSyncChangesRead)
def report_file_changes(
    agent_id: UUID,
    changes: FileSyncChangesCreate,
    service: Annotated[FileSyncIngestService, Injected(FileSyncIngestService)],
    authorization: Annotated[str, Header()],
) -> FileSyncChangesRead:
    return _answer(lambda: service.report_changes(agent_id, _key(authorization), changes))


@file_sync_ingest_router.post("/{agent_id}/file-sync/uploads/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_file_upload(
    agent_id: UUID,
    upload: FileSyncUploadCompleteCreate,
    service: Annotated[FileSyncIngestService, Injected(FileSyncIngestService)],
    authorization: Annotated[str, Header()],
):
    _answer(lambda: service.complete_upload(agent_id, _key(authorization), upload.path))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@file_sync_ingest_router.get("/{agent_id}/file-sync/operations", response_model=FileSyncOperationsRead)
def claim_file_operations(
    agent_id: UUID,
    service: Annotated[FileSyncIngestService, Injected(FileSyncIngestService)],
    authorization: Annotated[str, Header()],
) -> FileSyncOperationsRead:
    return _answer(lambda: service.claim_operations(agent_id, _key(authorization)))


@file_sync_ingest_router.post("/{agent_id}/file-sync/operations/result", status_code=status.HTTP_204_NO_CONTENT)
def report_file_operation_result(
    agent_id: UUID,
    result: FileSyncOperationResultCreate,
    service: Annotated[FileSyncIngestService, Injected(FileSyncIngestService)],
    authorization: Annotated[str, Header()],
):
    _answer(lambda: service.report_result(agent_id, _key(authorization), result))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
