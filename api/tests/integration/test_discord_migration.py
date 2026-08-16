from hamcrest import assert_that, contains_string, has_item
from sqlalchemy import create_engine, inspect

from api.core.config import get_config


def test_discord_migration_installs_config_table_and_platform_constraint():
    engine = create_engine(str(get_config().db_connection_url))
    inspector = inspect(engine)

    assert_that(inspector.get_table_names(), has_item("agent_discord_config"))
    indexes = inspector.get_indexes("agent_discord_config")
    index_names = [index["name"] for index in indexes if index["name"] is not None]
    assert "ix_agent_discord_config_bot_token_hash" in index_names
    constraints = inspector.get_check_constraints("agent")
    platform_constraint = next(item for item in constraints if item["name"] == "ck_agent_platform")
    assert_that(platform_constraint["sqltext"], contains_string("'discord'"))
