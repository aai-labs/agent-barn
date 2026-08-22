from hamcrest import assert_that, has_items, is_not
from sqlalchemy import create_engine, inspect

from api.core.config import get_config


def test_communications_cutover_removes_legacy_platform_schema():
    engine = create_engine(str(get_config().db_connection_url))
    inspector = inspect(engine)

    tables = inspector.get_table_names()
    assert_that(
        tables,
        has_items(
            "communication_connection",
            "communication_delivery",
        ),
    )
    for legacy_table in (
        "agent_slack_config",
        "agent_teams_config",
        "agent_telegram_config",
        "agent_discord_config",
    ):
        assert_that(tables, is_not(has_items(legacy_table)))
    assert "platform" not in {column["name"] for column in inspector.get_columns("agent")}
