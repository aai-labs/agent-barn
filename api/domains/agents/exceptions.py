from fastapi import status
from fastapi.exceptions import HTTPException

from api.domains.usage.models import SuspensionReason


class AgentProvisioningPrecondition(HTTPException):
    """Raised when a start request fails a check, such as an Agent already running.

    The Agent keeps its current status and its recorded error. Any other exception
    raised while provisioning moves the Agent to ERROR and records why it failed.
    """


class AgentLimitReached(HTTPException):
    """An Organization already runs as many Agents as it may."""

    def __init__(self, limit: int) -> None:
        agents = "one agent" if limit == 1 else f"{limit} agents"
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=f"This organization can have {agents}.")


_SUSPENDED = "This agent is suspended and can't start."
_SUSPENSION_MESSAGES = {
    SuspensionReason.TIER: "This agent is on hold because your organization's tier doesn't cover it. "
    "An owner or admin can release it when there's room.",
}


class AgentSuspended(HTTPException):
    """A suspended Agent can't start until it is resumed."""

    def __init__(self, reason: SuspensionReason | None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AGENT_SUSPENDED",
                "reason": reason.value if reason is not None else None,
                "message": _SUSPENSION_MESSAGES[reason] if reason is not None else _SUSPENDED,
            },
        )


class BotTokenConflictHTTPException(HTTPException):
    def __init__(self, agent_name: str, platform: str = "Slack"):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = (
            f"This {platform} bot token is already in use by agent '{agent_name}'. "
            f"Each agent must use a distinct {platform} app."
        )
