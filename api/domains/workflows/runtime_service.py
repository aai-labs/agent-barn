import json
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
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
    config: Config

    def handoff(self, attempt_id: UUID, token: str) -> dict:
        run, _, packet = self.repository.admit(attempt_id, token)
        if self.config.artifact_s3_endpoint_url:
            packet["file_publication"] = {
                "command": "/usr/local/bin/agentbarn-artifacts upload <workspace-file>",
                "required_arguments": {"--attempt-id": str(attempt_id)},
                "instructions": "Publish requested files before replying. Existing files are identified by exact artifact_id/checksum in completed_steps; use agentbarn-artifacts retrieve to read them. Never report a local path as a published artifact. Storage failure does not prevent an honest text-only result.",
            }
        context = json.dumps(packet, ensure_ascii=False)
        if len(context.encode()) > workflow_config.MAX_CONTEXT_BYTES:
            raise WorkflowConflict("Workflow context (summaries and file references) exceeds the context limit")
        return {"runtime": run.runtime, "session_id": f"workflow-{attempt_id}", "prompt": STEP_INSTRUCTIONS + context}
