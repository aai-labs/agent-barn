"""Whether a Task about to be marked done at the end of a turn is really finished.

The Task plugin marks the Task a turn worked on done unless the Agent asked to keep it in
progress. An Agent that asks a question, or starts a job that continues later, does not
always say so, and its Task was closed while the job was still going. So before closing,
the plugin reports the turn here and a decision model reads it: a Task whose job is still
going is held in progress, and one waiting on the user is held open.

The model can only hold a Task back. It never closes one, and a Task the Agent kept or set
a status on itself is not asked about. When the model fails or is unsure, nothing is held
and the plugin closes the Task as before.
"""

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from api.domains.agent_tasks.service import AgentTaskService
from api.domains.decisions.service import DecisionService
from api.infrastructure.litellm.decisions import ChoiceAnswer, ChoiceQuestion, DecisionError

logger = logging.getLogger(__name__)

_MAX_NOTES = 30
_NOTE_CHARS = 300
# Below this the model's answer holds nothing.
_MIN_CONFIDENCE = 0.7
# The model's answer -> the status the Task is held in.
_HOLDS: dict[str, Literal["in_progress", "open"]] = {"ongoing": "in_progress", "waiting": "open"}

_QUESTION = ChoiceQuestion(
    "A Task tracks one job the user gave an AI agent. Judge from the user's request what the whole job is, and "
    "from the reply, tool calls and the Task's notes and files how much of it has been delivered. Is the whole job "
    "delivered now?",
    {
        "finished": "Yes. Everything the user asked for in this job has been delivered. A single request answered "
        "in one turn is finished.",
        "ongoing": "No. Part of the job has not happened yet: the user asked for several parts, messages or "
        "scheduled runs and some remain, or the agent is waiting for a reply or an event from someone other than "
        "the user before it can finish.",
        "waiting": "No. The agent asked the user a question or needs something from the user before it can continue.",
    },
)


class AgentTaskTurnEnd(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(default="", max_length=8000)
    reply: str = Field(default="", max_length=8000)
    # One short line per tool call: the tool's name and its arguments.
    tools: list[str] = Field(default_factory=list, max_length=60)
    # The Tasks the plugin is about to mark done.
    closing: list[UUID] = Field(default_factory=list, max_length=20)
    # What started the turn, such as a scheduled run. Empty for a user's message.
    trigger: str = Field(default="", max_length=60)


class AgentTaskTurnEndRead(PydanticBaseModel):
    # Task id -> the status to leave it in instead of done. A Task that is not here is closed.
    holds: dict[str, Literal["in_progress", "open"]] = Field(default_factory=dict)


@inject
@singleton
@dataclass
class AgentTaskTurnEndService:
    tasks: AgentTaskService
    decisions: DecisionService

    def holds(self, organization_id: UUID, agent_id: UUID, data: AgentTaskTurnEnd) -> AgentTaskTurnEndRead:
        state_tasks: dict[str, dict] = {}
        for task_id in dict.fromkeys(data.closing):
            try:
                detail = self.tasks.get_own_task(organization_id, agent_id, task_id)
            except HTTPException:
                continue
            state_tasks[str(task_id)] = {
                "title": detail.title,
                "description": detail.description or "",
                "notes_oldest_first": [note.body[:_NOTE_CHARS] for note in detail.notes[-_MAX_NOTES:]],
                "files_attached": [file.filename for file in detail.files],
            }
        if not state_tasks:
            return AgentTaskTurnEndRead()
        state = {
            "turn": {
                "trigger": data.trigger or "user message",
                "request": data.request,
                "agent_reply": data.reply,
                "tool_calls": data.tools,
            },
            "tasks": state_tasks,
        }
        try:
            answers = self.decisions.decide(agent_id, state, dict.fromkeys(state_tasks, _QUESTION)).answers
        except DecisionError as error:
            logger.warning("Task turn-end decision failed for agent %s: %s", agent_id, error.failure.value)
            return AgentTaskTurnEndRead()
        holds: dict[str, Literal["in_progress", "open"]] = {}
        for task_id in state_tasks:
            answer = answers.get(task_id)
            if isinstance(answer, ChoiceAnswer) and answer.confidence >= _MIN_CONFIDENCE and answer.choice in _HOLDS:
                holds[task_id] = _HOLDS[answer.choice]
        return AgentTaskTurnEndRead(holds=holds)
