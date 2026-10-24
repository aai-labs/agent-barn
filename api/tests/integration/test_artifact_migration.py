from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from hamcrest import assert_that, equal_to
from sqlalchemy import create_engine, inspect
from sqlmodel import Session

from api.domains.artifacts.models import Artifact
from api.tests.integration.test_rbac_schema import isolated_database  # noqa: F401


def test_upgrade_and_guarded_downgrade_preserve_cleanup_evidence(isolated_database):  # noqa: F811
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(isolated_database)
    row = Artifact(
        organization_id=uuid4(),
        agent_id=uuid4(),
        filename="report.csv",
        size=0,
        content_type="text/csv",
        checksum="a" * 64,
        bucket="fixture-bucket",
        object_key="fixture-key",
        source="chat",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        artifact_id = row.id
    with pytest.raises(RuntimeError, match="Purge retained artifact bytes"):
        command.downgrade(config, "f8740a67b788")
    with Session(engine) as session:
        retained = session.get_one(Artifact, artifact_id)
        assert_that(retained.state, equal_to("UPLOADING"))
        retained.state = "DELETED"
        session.add(retained)
        session.commit()
    command.downgrade(config, "f8740a67b788")
    assert_that(inspect(engine).has_table("artifact"), equal_to(False))
    command.upgrade(config, "head")
    assert_that(inspect(engine).has_table("artifact_reference"), equal_to(True))
    engine.dispose()
