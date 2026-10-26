import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import WORKFLOW_CONTROLLER_HANDLER, WORKFLOW_RUN_CHANGED
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.handlers import EventDeliveryContext, SupportedEvent
from api.domains.events.models import DomainEventEnvelope
from api.domains.workflows.run_models import TERMINAL_STATES, WorkflowRun
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient

logger = logging.getLogger(__name__)

TRIGGER_PORT = 8082
STEPS_PATH = "/agent-triggers/v1/workflow-steps"


@inject
@singleton
@dataclass
class WorkflowController:
    """Sends each step to its Agent once, as a new session in the running Agent."""

    repository: WorkflowRunRepository
    agents: AgentRepository
    k8s: KubernetesClient
    config: Config
    dispatcher: EventDeliveryDispatcher

    def wake(self, run_id: UUID) -> None:
        inspected = self.repository.inspect(run_id)
        if inspected is None:
            return
        if inspected[0].state in TERMINAL_STATES:
            return
        # advance first closes admission, independently of the Agent's reachability.
        _, delivery_ids = self.repository.advance(run_id)
        self.dispatcher.enqueue_immediate(delivery_ids)
        run, attempt = self.repository.inspect(run_id) or inspected
        if attempt is None:
            return
        if attempt.state == "STOPPING":
            # Results from a stopped attempt are fenced; stopping the session is best effort.
            if attempt.dispatched_at is not None:
                self._send(run, f"{STEPS_PATH}/{attempt.id}/stop", {})
            _, delivery_ids = self.repository.advance(run_id, stopped=True)
            self.dispatcher.enqueue_immediate(delivery_ids)
            return
        if (
            attempt.state != "REASONING"
            or run.state != "RUNNING"
            or attempt.dispatched_at is not None
            or attempt.expires_at <= datetime.now(UTC)
        ):
            return
        status = self._send(
            run,
            STEPS_PATH,
            {
                "attempt_id": str(attempt.id),
                "token": self.repository.token(attempt.id),
                "callback_url": self.config.workflow_runtime_base_url.rstrip("/") + f"/attempts/{attempt.id}",
            },
        )
        # 409 means the Agent already holds this attempt (a lost acknowledgement).
        if status in (202, 409):
            self.repository.mark_dispatched(attempt.id)

    def _send(self, run: WorkflowRun, path: str, payload: dict) -> int | None:
        agent_id = self.repository.owning_agent_id(run.workflow_id)
        agent = self.agents.get_by_id(agent_id)
        if agent is None or not agent.communication_key_encrypted:
            return None
        key = decrypt_token(agent.communication_key_encrypted, self.config.agent_token_encryption_key)
        try:
            status, _, _ = self.k8s.proxy_to_agent(
                f"agent-{agent_id}",
                self.config.k8s_namespace,
                TRIGGER_PORT,
                path,
                "POST",
                json.dumps(payload).encode(),
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        except Exception:
            # Unreachable Agents are retried on the next pass until the attempt expires.
            logger.warning("Workflow run %s could not reach its Agent", run.id)
            return None
        if status not in (202, 409):
            logger.warning("Workflow run %s Agent dispatch returned HTTP %s", run.id, status)
        return status


@inject
@singleton
@dataclass
class WorkflowControllerHandler:
    controller: WorkflowController
    name: ClassVar[str] = WORKFLOW_CONTROLLER_HANDLER
    supported_events: ClassVar[tuple[SupportedEvent, ...]] = (SupportedEvent(WORKFLOW_RUN_CHANGED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        # Dispatch is a plain HTTP call to the Agent, so the event worker sends steps
        # immediately; the scheduled pass only recovers missed wakeups.
        self.controller.wake(UUID(str(event.payload["run_id"])))
