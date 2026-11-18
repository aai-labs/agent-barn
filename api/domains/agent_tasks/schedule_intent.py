"""Whether the runs of a schedule an Agent just created are part of the Task that tracks the request.

"Remind me every morning" is finished once the schedule exists. "Post a greeting daily for a
week, done after 7" is finished only after those runs. The schedule looks the same either
way, so a decision model reads the user's request once, when the schedule is created. The
Task plugin then follows the schedule itself; no model is asked again.
"""

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from injector import inject, singleton
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from api.domains.decisions.service import DecisionService
from api.infrastructure.litellm.decisions import ChoiceAnswer, ChoiceQuestion, DecisionError

logger = logging.getLogger(__name__)

_QUESTION = ChoiceQuestion(
    "The agent just created a schedule for the user. For the Task that tracks this request, what did the user ask for?",
    {
        "setup": "A standing arrangement: the user wants the schedule to exist (a reminder, a recurring report, a "
        "routine). Once the schedule is created, the request is fulfilled.",
        "runs": "A bounded piece of work carried out by the scheduled runs: the user gave a number of runs, an end "
        "date or a condition for when it is done, so it is only finished after those runs have happened.",
    },
)


class ScheduleRead(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    # How the runtime describes when the schedule fires, such as "every 1d" or a cron expression.
    recurrence: str = Field(default="", max_length=200)
    run_limit: int | None = Field(default=None, ge=1)


class ScheduledTaskRead(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=500)
    # The status the Agent left the Task in, which the model may disagree with.
    status: str = Field(default="", max_length=20)


class ScheduleIntentRequest(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(default="", max_length=8000)
    schedule: ScheduleRead = Field(default_factory=ScheduleRead)
    task: ScheduledTaskRead = Field(default_factory=ScheduledTaskRead)


class ScheduleIntentRead(PydanticBaseModel):
    # None when no decision was made; the plugin then goes by what the Agent did.
    intent: Literal["setup", "runs"] | None


@inject
@singleton
@dataclass
class ScheduleIntentService:
    decisions: DecisionService

    def decide(self, agent_id: UUID, data: ScheduleIntentRequest) -> ScheduleIntentRead:
        state = {
            "request": data.request,
            "schedule": {"recurrence": data.schedule.recurrence, "run_limit": data.schedule.run_limit},
            "task": {"title": data.task.title, "status_the_agent_set": data.task.status},
        }
        try:
            answer = self.decisions.decide(agent_id, state, {"intent": _QUESTION}).answers["intent"]
        except DecisionError as error:
            logger.warning("Schedule intent decision failed for agent %s: %s", agent_id, error.failure.value)
            return ScheduleIntentRead(intent=None)
        if not isinstance(answer, ChoiceAnswer) or answer.choice not in ("setup", "runs"):
            return ScheduleIntentRead(intent=None)
        return ScheduleIntentRead(intent=answer.choice)
