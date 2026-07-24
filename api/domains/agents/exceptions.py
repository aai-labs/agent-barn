from fastapi import status
from fastapi.exceptions import HTTPException


class BotTokenConflictHTTPException(HTTPException):
    def __init__(self, agent_name: str):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = (
            f"This Slack bot token is already in use by agent '{agent_name}'. Each agent must use a distinct Slack app."
        )
