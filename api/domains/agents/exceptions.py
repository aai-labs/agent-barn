from fastapi import status
from fastapi.exceptions import HTTPException


class AgentProvisioningPrecondition(HTTPException):
    """Raised when a start request fails a check, such as an Agent already running.

    The Agent keeps its current status and its recorded error. Any other exception
    raised while provisioning moves the Agent to ERROR and records why it failed.
    """


class BotTokenConflictHTTPException(HTTPException):
    def __init__(self, agent_name: str, platform: str = "Slack"):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = (
            f"This {platform} bot token is already in use by agent '{agent_name}'. "
            f"Each agent must use a distinct {platform} app."
        )
