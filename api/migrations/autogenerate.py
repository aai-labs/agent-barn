"""Protect rollout-only columns until deployed legacy readers and writers exit."""

from sqlalchemy import Column
from sqlalchemy.schema import SchemaItem

_RETAINED_CONNECTION_COLUMNS = {"driver_key_encrypted", "ingress_lease_owner", "ingress_lease_expires_at"}


def include_object(
    object_: SchemaItem, name: str | None, type_: str, reflected: bool, compare_to: SchemaItem | None
) -> bool:
    # Explicit contraction migrations must wait for the operations runbook cutoff.
    return not (
        type_ == "column"
        and reflected
        and compare_to is None
        and isinstance(object_, Column)
        and object_.table.name == "communication_connection"
        and name in _RETAINED_CONNECTION_COLUMNS
    )
