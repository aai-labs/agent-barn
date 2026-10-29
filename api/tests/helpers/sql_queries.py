from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event


@contextmanager
def capture_sql_statements(engine: Engine) -> Iterator[list[str]]:
    """Capture statement shapes without parameter values or credential contents."""
    statements: list[str] = []

    def capture(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)
