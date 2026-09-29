from fastapi import status
from fastapi.exceptions import HTTPException


class MemoryGroupNameConflictHTTPException(HTTPException):
    def __init__(self, name: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A memory group named '{name}' already exists in this organization",
        )
