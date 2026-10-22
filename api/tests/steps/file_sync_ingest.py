from fastapi import status
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentType
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncActivity, SyncActivityKind, SyncAgentFolder, SyncFile
from api.domains.sync_provider.plugins.base import RemoteItemMissing
from api.infrastructure.crypto import encrypt_token
from api.tests.core.modules import prepare_ingest_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.file_sync_provider import TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization

AGENT_KEY = "agent-ingest-key"
SHA_A = "a" * 64
SHA_B = "b" * 64


def file_sync_ingest_base(*, clean_database: bool = False) -> list:
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[TestDriveModule()]),
        database_repo_is_ready(),
        *([database_is_clean()] if clean_database else []),
        prepare_ingest_server(),
        there_is_an_organization(),
    ]


def ready_agent(context, agent_type: AgentType = AgentType.OPENCLAW) -> Agent:
    there_is_an_agent(name="Sales Bot", agent_type=agent_type)(context)
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(Agent, context.agent.id)
        assert row is not None
        row.ingest_key_encrypted = encrypt_token(AGENT_KEY, TEST_ENCRYPTION_KEY)
        session.add(row)
        session.commit()
    there_is_a_sync_connection()(context)
    context.injector.get(FileSyncEngine).reconcile_folders(context.connection)
    return context.agent


def file_entry(path: str, sha: str = SHA_A, size: int = 5) -> dict:
    return {"path": path, "size": size, "sha256": sha}


def report_files(context, agent: Agent, *entries: dict, complete: bool = True):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/changes",
        json={"complete": complete, "entries": list(entries)},
        headers={"Authorization": f"Bearer {AGENT_KEY}"},
    )


def complete_upload(context, agent: Agent, path: str, key: str = AGENT_KEY):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/uploads/complete",
        json={"path": path},
        headers={"Authorization": f"Bearer {key}"},
    )


def agent_folder(context) -> SyncAgentFolder:
    with Session(context.postgres_delegate.engine) as session:
        folder = session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.agent_id) == context.agent.id)).first()
        assert folder is not None
        return folder


def synced_files(context) -> dict[str, SyncFile]:
    with Session(context.postgres_delegate.engine) as session:
        rows = session.exec(select(SyncFile).where(col(SyncFile.folder_id) == agent_folder(context).id))
        return {row.path: row for row in rows}


def activity_entries(context) -> list[tuple[SyncActivityKind, str | None]]:
    with Session(context.postgres_delegate.engine) as session:
        rows = session.exec(select(SyncActivity).where(col(SyncActivity.agent_id) == context.agent.id))
        return [(row.kind, row.path) for row in rows]


def upload_through_the_pod(context, agent: Agent, path: str, content: bytes) -> None:
    response = report_files(context, agent, file_entry(path, size=len(content)))
    upload = next(upload for upload in response.json()["uploads"] if upload["path"] == path)
    fake_drive(context).complete_upload(upload["url"], content)
    assert complete_upload(context, agent, path).status_code == status.HTTP_204_NO_CONTENT


def provider_has(context, path: str) -> bool:
    folder_item_id = agent_folder(context).folder_item_id
    assert folder_item_id is not None
    try:
        fake_drive(context).get_item_by_path(context.sync_root, parent_id=folder_item_id, rel_path=path)
    except RemoteItemMissing:
        return False
    return True
