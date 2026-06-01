import datetime
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import AgentType
from api.domains.agents.repository import AgentRepository
from api.domains.conversations.hermes_parser import (
    HERMES_SESSIONS_PATH,
    parse_hermes_export_tool_calls,
)
from api.domains.tool_calls.jsonl_parser import parse_jsonl
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.kubernetes.client import KubernetesClient

logger = logging.getLogger(__name__)

_SESSIONS_DIR = "/home/node/.openclaw/agents/main/sessions"
_MIN_SYNC_INTERVAL_SECONDS = 4


@inject
@singleton
@dataclass
class ToolCallSyncService:
    k8s: KubernetesClient
    repository: ToolCallRepository
    agent_repository: AgentRepository
    config: Config
    _executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=8), init=False
    )

    def sync_agent(self, agent_id: UUID, org_id: UUID, *, force: bool = False) -> None:
        """Pull new tool calls from the agent pod. Blocks until complete. Swallows all errors."""
        if not force:
            last_synced = self.repository.get_most_recent_sync_time(agent_id)
            if last_synced is not None:
                age = (
                    datetime.datetime.now(datetime.timezone.utc) - last_synced
                ).total_seconds()
                if age < _MIN_SYNC_INTERVAL_SECONDS:
                    return
        try:
            agent = self.agent_repository.get_by_id(agent_id)
            if agent and agent.agent_type == AgentType.HERMES:
                self._do_sync_hermes(agent_id, org_id)
            else:
                self._do_sync(agent_id, org_id)
        except Exception:
            logger.warning("Sync failed for agent %s", agent_id, exc_info=True)

    def _do_sync(self, agent_id: UUID, org_id: UUID) -> None:
        ns = self.config.k8s_namespace
        pod_name = self.k8s.get_pod_name_for_deployment(f"agent-{agent_id}", ns)
        if pod_name is None:
            return

        try:
            ls_output = self.k8s.exec_command(
                pod_name,
                ns,
                [
                    "find",
                    _SESSIONS_DIR,
                    "-name",
                    "*.jsonl",
                    "-not",
                    "-name",
                    "*.trajectory.jsonl",
                ],
            )
        except RuntimeError:
            logger.debug("Could not list session files for agent %s", agent_id)
            return

        files = [p.strip() for p in ls_output.splitlines() if p.strip()]
        list(
            self._executor.map(
                lambda f: self._sync_file_safe(agent_id, org_id, pod_name, ns, f),
                files,
            )
        )

    def _do_sync_hermes(self, agent_id: UUID, org_id: UUID) -> None:
        ns = self.config.k8s_namespace
        pod_name = self.k8s.get_pod_name_for_deployment(f"agent-{agent_id}", ns)
        if pod_name is None:
            return

        try:
            raw_sessions = self.k8s.exec_command(pod_name, ns, ["cat", HERMES_SESSIONS_PATH])
        except RuntimeError:
            logger.debug("Could not read hermes sessions.json for agent %s", agent_id)
            return

        try:
            sessions = json.loads(raw_sessions)
        except json.JSONDecodeError:
            return

        for session_key, session_data in sessions.items():
            if not isinstance(session_data, dict):
                continue
            session_id = session_data.get("session_id")
            if not session_id:
                continue
            if session_data.get("tool_call_count") == 0:
                continue

            # Use updated_at epoch-ms as version — skip if unchanged since last sync.
            updated_at_str = session_data.get("updated_at") or ""
            try:
                version = int(
                    datetime.datetime.fromisoformat(updated_at_str).timestamp() * 1000
                )
            except (ValueError, AttributeError):
                version = 0

            sync_key = f"hermes:{session_id}"
            sync_state = self.repository.get_sync_state(agent_id, sync_key)
            if sync_state and sync_state.last_byte_offset == version:
                continue

            try:
                export_raw = self.k8s.exec_command(
                    pod_name,
                    ns,
                    ["hermes", "sessions", "export", "--session-id", session_id, "-"],
                )
            except RuntimeError:
                logger.debug("Could not export hermes session %s", session_id)
                continue

            for line in export_raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                tool_calls, tool_results = parse_hermes_export_tool_calls(line, session_id)
                with self.repository.get_session() as db_session:
                    for tc in tool_calls:
                        self.repository.upsert_pending(
                            db_session,
                            organization_id=org_id,
                            agent_id=agent_id,
                            session_id=tc.session_id,
                            external_id=tc.external_id,
                            tool_name=tc.tool_name,
                            arguments=tc.arguments,
                            occurred_at=tc.occurred_at,
                        )
                    for tr in tool_results:
                        self.repository.complete(
                            db_session,
                            agent_id=agent_id,
                            external_id=tr.external_id,
                            result=tr.result,
                            is_error=tr.is_error,
                            completed_at=tr.completed_at,
                        )
                    self.repository.save_sync_state(db_session, agent_id, sync_key, version)
                    db_session.commit()

    def _sync_file_safe(
        self,
        agent_id: UUID,
        org_id: UUID,
        pod_name: str,
        ns: str,
        file_path: str,
    ) -> None:
        try:
            self._sync_file(agent_id, org_id, pod_name, ns, file_path)
        except Exception:
            logger.warning(
                "Failed to sync %s for agent %s", file_path, agent_id, exc_info=True
            )

    def _sync_file(
        self,
        agent_id: UUID,
        org_id: UUID,
        pod_name: str,
        ns: str,
        file_path: str,
    ) -> None:
        session_id = PurePosixPath(file_path).stem

        sync_state = self.repository.get_sync_state(agent_id, file_path)
        offset = sync_state.last_byte_offset if sync_state else 0

        try:
            raw = self.k8s.exec_command(
                pod_name,
                ns,
                ["tail", "-c", f"+{offset + 1}", file_path],
            )
        except RuntimeError:
            return

        if not raw:
            return

        tool_calls, tool_results = parse_jsonl(raw, session_id)
        new_offset = offset + len(raw.encode("utf-8"))

        with self.repository.get_session() as session:
            for tc in tool_calls:
                self.repository.upsert_pending(
                    session,
                    organization_id=org_id,
                    agent_id=agent_id,
                    session_id=tc.session_id,
                    external_id=tc.external_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    occurred_at=tc.occurred_at,
                )
            for tr in tool_results:
                self.repository.complete(
                    session,
                    agent_id=agent_id,
                    external_id=tr.external_id,
                    result=tr.result,
                    is_error=tr.is_error,
                    completed_at=tr.completed_at,
                )
            self.repository.save_sync_state(session, agent_id, file_path, new_offset)
            session.commit()
