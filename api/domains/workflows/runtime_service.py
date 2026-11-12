import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.workflows import config as workflow_config
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_models import ApprovalRaised
from api.domains.workflows.run_repository import WorkflowRunRepository

STEP_INSTRUCTIONS = (
    "You are running one step of a saved workflow. Complete only the current step, using the supplied "
    "inputs and the summaries of earlier steps. You may use your normal tools and connected integrations; "
    "your usual approval rules apply. Do not invent facts or claim actions you did not take.\n"
    'When you are done, reply with ONLY a JSON object: {"summary": string, "criteria_met": boolean}. '
    "The summary must contain the actual result and any facts later steps need, in at most 4000 characters, "
    "following output_description and final_output_description. Format the summary as readable Markdown, "
    "using short paragraphs, headings or lists where useful. Describe published files by name; do not include "
    "artifact download URLs or expiring links, since the workflow displays downloadable attachments. "
    "If the step cannot be completed, set "
    "criteria_met to false and explain why in the summary.\n"
)


def continuation_prompt(state: str, command: str, guidance: str | None) -> str:
    """Resumes a step's own session after a person decided on the command it asked to run."""
    if state == "APPROVED":
        decided = (
            f"A person approved the command you asked to run:\n{command}\n"
            "If it is still needed, run it now; you may be asked for approval again."
        )
    else:
        decided = (
            f"A person declined the command you asked to run:\n{command}\n"
            "Do not run it. Their guidance: " + (guidance or "none given") + "\nFollow the guidance."
        )
    return (
        decided + "\nContinue this workflow step where you left off. Do not repeat actions you already "
        "completed in this conversation. When you are done, reply with ONLY the JSON result object as instructed.\n"
    )


@inject
@singleton
@dataclass
class WorkflowRuntimeService:
    repository: WorkflowRunRepository
    config: Config
    dispatcher: EventDeliveryDispatcher

    def handoff(self, attempt_id: UUID, token: str) -> dict:
        run, _, packet = self.repository.admit(attempt_id, token)
        continuation = packet.pop("continuation", None)
        if continuation:
            # The resumed session already holds the step's instructions and context.
            return {
                "runtime": run.runtime,
                "session_id": continuation["session_id"],
                "resume": True,
                "prompt": continuation_prompt(continuation["state"], continuation["command"], continuation["guidance"]),
                "files": packet["files"],
            }
        if self.config.artifact_s3_endpoint_url:
            packet["file_publication"] = {
                "command": "/usr/local/bin/agentbarn-artifacts upload <workspace-file>",
                "required_arguments": {"--attempt-id": str(attempt_id)},
                "instructions": "Publish requested files before replying. Existing files are identified by exact artifact_id/checksum in completed_steps; use agentbarn-artifacts retrieve to read them. Never report a local path as a published artifact. Use the step and final output descriptions to decide whether a file is needed and which format serves the user. Every generated file must be published so it is downloadable. A description alone is not a published file. If you cannot produce or publish a requested deliverable, report that honestly and set criteria_met to false.",
            }
        context = json.dumps(packet, ensure_ascii=False)
        if len((STEP_INSTRUCTIONS + context).encode()) > workflow_config.MAX_CONTEXT_BYTES:
            raise WorkflowConflict("Workflow context (summaries and file references) exceeds the context limit")
        return {
            "runtime": run.runtime,
            "session_id": f"workflow-{attempt_id}",
            "resume": False,
            "prompt": STEP_INSTRUCTIONS + context,
            "files": packet["files"],
        }

    def raise_approval(self, attempt_id: UUID, token: str, raised: ApprovalRaised) -> dict:
        request, delivery_ids = self.repository.raise_approval(attempt_id, token, raised)
        self.dispatcher.enqueue_immediate(delivery_ids)
        # A retried report gets the time actually left, never a fresh window.
        remaining = (request.live_until - datetime.now(UTC)).total_seconds()
        return {"id": str(request.id), "live_seconds": max(remaining, 0)}

    def approval_status(self, attempt_id: UUID, token: str, request_id: UUID) -> dict:
        request = self.repository.approval_status(attempt_id, token, request_id)
        status: dict = {"state": request.state}
        if request.state == "DECLINED":
            status["prompt"] = continuation_prompt(request.state, request.command, request.guidance)
        return status

    def park(self, attempt_id: UUID, token: str, request_id: UUID) -> dict:
        """Close the live window; a decision that won the race is returned for the step to act on."""
        request, delivery_ids = self.repository.park(attempt_id, token, request_id)
        self.dispatcher.enqueue_immediate(delivery_ids)
        if request.state == "PARKED":
            return {"state": "PARKED"}
        return self.approval_status(attempt_id, token, request_id)

    def released(self, attempt_id: UUID, token: str, request_id: UUID) -> None:
        self.dispatcher.enqueue_immediate(self.repository.released(attempt_id, token, request_id))
