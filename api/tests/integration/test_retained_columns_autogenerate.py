import os

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine

from api.migrations.autogenerate import include_object


def test_autogenerate_preserves_only_unmapped_legacy_connection_columns():
    engine = create_engine(os.environ["DB_CONNECTION_URL"])
    try:
        with engine.connect() as connection, connection.begin():
            # A rolled-back private schema keeps the real migrated test database intact.
            connection.exec_driver_sql("CREATE SCHEMA retirement_autogenerate")
            connection.exec_driver_sql("SET LOCAL search_path TO retirement_autogenerate")
            historical = MetaData()
            retained = ["driver_key_encrypted", "ingress_lease_owner", "ingress_lease_expires_at"]
            Table(
                "communication_connection",
                historical,
                Column("id", Integer, primary_key=True),
                *(Column(name, Text) for name in retained),
                Column("unrelated_obsolete", Text),
                Column("changed", Text),
            )
            Table("other_resource", historical, Column("id", Integer), Column("driver_key_encrypted", Text))
            historical.create_all(connection)
            current = MetaData()
            Table(
                "communication_connection",
                current,
                Column("id", Integer, primary_key=True),
                Column("changed", Integer),
                Column("new_field", Text),
            )
            Table("other_resource", current, Column("id", Integer))
            plain = compare_metadata(MigrationContext.configure(connection), current)
            guarded = compare_metadata(
                MigrationContext.configure(connection, opts={"include_object": include_object, "compare_type": True}),
                current,
            )
            removed = lambda diffs: {(diff[2], diff[3].name) for diff in diffs if diff[0] == "remove_column"}
            assert {("communication_connection", name) for name in retained} <= removed(plain)
            assert removed(guarded) == {
                ("communication_connection", "unrelated_obsolete"),
                ("other_resource", "driver_key_encrypted"),
            }
            assert any(diff[0] == "add_column" and diff[3].name == "new_field" for diff in guarded)
            assert any(isinstance(diff, list) and diff[0][0] == "modify_type" for diff in guarded)
            connection.rollback()
    finally:
        engine.dispose()
