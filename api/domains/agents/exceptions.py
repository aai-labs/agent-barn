from fastapi import status
from fastapi.exceptions import HTTPException


class BotTokenConflictHTTPException(HTTPException):
    def __init__(self, agent_name: str, platform: str = "Slack"):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = (
            f"This {platform} bot token is already in use by agent '{agent_name}'. "
            f"Each agent must use a distinct {platform} app."
        )
