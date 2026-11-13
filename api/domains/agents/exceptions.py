from fastapi import status
from fastapi.exceptions import HTTPException

from api.domains.agents.models import Agent


class AgentProvisioningPrecondition(HTTPException):
    """Raised when a start request fails a check, such as an Agent already running.

    The Agent keeps its current status and its recorded error. Any other exception
    raised while provisioning moves the Agent to ERROR and records why it failed.
    """


def refuse_on_bot(agent: Agent) -> None:
    if agent.parent_agent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This Bot runs inside Parent Agent {agent.parent_agent_id}. Do this on the Parent Agent.",
        )


class AgentLimitReached(HTTPException):
    """An Organization already runs as many Agents as it may."""

    def __init__(self, limit: int) -> None:
        agents = "one agent" if limit == 1 else f"{limit} agents"
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=f"This organization can have {agents}.")


class BotTokenConflictHTTPException(HTTPException):
    def __init__(self, agent_name: str, platform: str = "Slack"):
        self.status_code = status.HTTP_409_CONFLICT
        self.detail = (
            f"This {platform} bot token is already in use by agent '{agent_name}'. "
            f"Each agent must use a distinct {platform} app."
        )
