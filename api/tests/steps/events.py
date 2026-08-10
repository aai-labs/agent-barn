from sqlalchemy import text

from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def event_delivery_tables_are_clean():
    """Truncate Outbox Message/Event Delivery rows.

    ``database_is_clean`` doesn't touch these tables, so Event Delivery Monitor tests
    need this to avoid cross-test pollution of global summary counts.
    """

    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        with delegate.engine.begin() as connection:
            connection.execute(text("TRUNCATE event_outbox_message CASCADE"))

    return step
