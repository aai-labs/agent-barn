import json
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.workflows import config as workflow_config
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_repository import WorkflowRunRepository

STEP_INSTRUCTIONS = (
    "You are running one step of a saved workflow. Complete only the current step, using the supplied "
    "inputs and the summaries of earlier steps. You may use your normal tools and connected integrations; "
    "your usual approval rules apply. Do not invent facts or claim actions you did not take.\n"
    'When you are done, reply with ONLY a JSON object: {"summary": string, "criteria_met": boolean}. '
    "The summary must contain the actual result and any facts later steps need, in at most 4000 characters, "
    "following output_description and final_output_description. If the step cannot be completed, set "
    "criteria_met to false and explain why in the summary.\n"
)


@inject
@singleton
@dataclass
class WorkflowRuntimeService:
    repository: WorkflowRunRepository

    def handoff(self, attempt_id: UUID, token: str) -> dict:
        run, _, packet = self.repository.admit(attempt_id, token)
        context = json.dumps(packet, ensure_ascii=False)
        if len(context.encode()) > workflow_config.MAX_CONTEXT_BYTES:
            raise WorkflowConflict("Earlier step summaries exceed the workflow context limit")
        return {"runtime": run.runtime, "session_id": f"workflow-{attempt_id}", "prompt": STEP_INSTRUCTIONS + context}
