from fastapi import status
from fastapi.exceptions import HTTPException


class EmailTakenHTTPException(HTTPException):
    def __init__(self, email: str):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = f"User with email {email} already exists."
