from fastapi import status
from fastapi.exceptions import HTTPException


class SharedCredentialNameConflictHTTPException(HTTPException):
    def __init__(self, name: str):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = f"A shared credential named '{name}' already exists in this organization"
