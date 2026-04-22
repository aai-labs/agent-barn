import os
from logging.config import fileConfig

import alembic_postgresql_enum  # noqa: F401
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import api.domains.auth.models  # noqa: F401
import api.domains.organizations.models  # noqa: F401
import api.domains.users.organization_users.models  # noqa: F401
import api.domains.users.models  # noqa: F401
from api.core.config import get_config

config = context.config
connection_url = str(get_config().db_connection_url)

db_url_override = os.environ.get("ALEMBIC_DB_URL")
if db_url_override and db_url_override != "":
    connection_url = db_url_override

config.set_main_option("sqlalchemy.url", connection_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
