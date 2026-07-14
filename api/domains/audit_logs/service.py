import csv
import io
import json
import logging
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject, singleton

from api.domains.audit_logs.models import (
    READ_ACTIONS,
    AuditAction,
    AuditLog,
    AuditLogFilter,
    AuditLogRead,
)
from api.domains.audit_logs.repository import AuditLogRepository, _OrgScope
from api.domains.auth.models import CurrentUserContext
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"

# Sentinel distinguishing "org not supplied, default from context" from an explicit
# ``organization_id=None`` (a deliberately global/NULL-org event).
_UNSET = object()

# Reads for the same (actor, action, target) within this window are collapsed to one row,
# so React Query refetch-on-focus doesn't flood the log. Best-effort and per-process.
_READ_SUPPRESSION_SECONDS = 300

_EXPORT_MAX_ROWS = 100_000

_EXPORT_COLUMNS = [
    "timestamp",
    "actor_email",
    "actor_name",
    "action",
    "organization_id",
    "organization_name",
    "target_type",
    "target_id",
    "target_label",
    "changed_fields",
    "id",
]


def redact_changed_fields(
    changed: Mapping[str, Any], value_allowlist: set[str]
) -> dict[str, Any]:
    """Default-deny: keep the value only for allowlisted field names; every other field
    is recorded by name with its value replaced by ``[redacted]``. New/unknown fields are
    therefore safe by construction — only an explicit allowlist entry can expose a value."""
    result: dict[str, Any] = {}
    for name, value in changed.items():
        result[name] = value if name in value_allowlist else REDACTED
    return result


def diff_changed_fields(
    before: Any,
    update_payload: Mapping[str, Any],
    value_allowlist: set[str],
) -> dict[str, Any]:
    """Build ``{field: {"old", "new"}}`` from a pre-update model and an update payload
    (typically ``model_dump(exclude_unset=True)``). Only fields whose value actually
    changed are included; non-allowlisted fields show ``[redacted]`` for both sides."""
    diff: dict[str, Any] = {}
    for name, new_value in update_payload.items():
        old_value = getattr(before, name, None)
        if old_value == new_value:
            continue
        if name in value_allowlist:
            diff[name] = {"old": _jsonable(old_value), "new": _jsonable(new_value)}
        else:
            diff[name] = {"old": REDACTED, "new": REDACTED}
    return diff


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


@inject
@singleton
@dataclass
class AuditLogService:
    repository: AuditLogRepository

    def __post_init__(self) -> None:
        self._read_seen: dict[tuple[UUID | None, str, UUID | None], float] = {}
        self._read_lock = threading.Lock()

    # --- write path ---

    def record(
        self,
        *,
        action: AuditAction | str,
        context: CurrentUserContext | None = None,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
        organization_id: Any = _UNSET,
        target_type: str | None = None,
        target_id: UUID | None = None,
        target_label: str | None = None,
        changed_fields: dict[str, Any] | None = None,
    ) -> None:
        """Persist one audit row. Never raises — an audit failure must not fail the
        user's request. Call as the last statement of a service method (i.e. after the
        repository commit) so only successful actions are recorded."""
        try:
            action_value = str(action)

            actor_id = actor_user_id
            actor_email_val = actor_email
            actor_name_val = None
            is_superuser_actor = False
            if context is not None:
                actor_id = context.user.id
                actor_email_val = context.user.email
                actor_name_val = context.user.full_name
                is_superuser_actor = context.user.is_superuser

            if organization_id is _UNSET:
                org_id = None
                if (
                    context is not None
                    and context.current_user_organization is not None
                ):
                    org_id = context.current_user_organization.organization_id
            else:
                org_id = organization_id

            if action_value in READ_ACTIONS and self._is_suppressed_read(
                actor_id, action_value, target_id
            ):
                return

            self.repository.save(
                AuditLog(
                    organization_id=org_id,
                    actor_user_id=actor_id,
                    actor_email=actor_email_val,
                    actor_name=actor_name_val,
                    is_superuser_actor=is_superuser_actor,
                    action=action_value,
                    target_type=target_type,
                    target_id=target_id,
                    target_label=target_label,
                    changed_fields=changed_fields or None,
                )
            )
        except Exception:
            logger.exception("Failed to write audit log for action %s", action)

    def _is_suppressed_read(
        self, actor_id: UUID | None, action: str, target_id: UUID | None
    ) -> bool:
        key = (actor_id, action, target_id)
        now = time.monotonic()
        with self._read_lock:
            last = self._read_seen.get(key)
            if last is not None and (now - last) < _READ_SUPPRESSION_SECONDS:
                return True
            self._read_seen[key] = now
            # Opportunistic cleanup so the map can't grow unbounded.
            if len(self._read_seen) > 10_000:
                cutoff = now - _READ_SUPPRESSION_SECONDS
                self._read_seen = {
                    k: v for k, v in self._read_seen.items() if v >= cutoff
                }
        return False

    # --- read path ---

    @staticmethod
    def _resolve_scope(
        context: CurrentUserContext, filters: AuditLogFilter
    ) -> _OrgScope:
        if context.user.is_superuser:
            if filters.scope == "all":
                return _OrgScope(all_orgs=True)
            if filters.organization_id is not None:
                return _OrgScope(organization_id=filters.organization_id)
        # Non-superusers (and superusers not asking for another org) see only the org
        # resolved from the request. The route's role gate already required manager rights.
        org_id = context.require_current_user_organization().organization_id
        return _OrgScope(organization_id=org_id)

    def list_logs(
        self,
        context: CurrentUserContext,
        filters: AuditLogFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AuditLogRead]:
        scope = self._resolve_scope(context, filters)
        return self.repository.find_paginated(scope, filters, pagination)

    def iter_export_rows(
        self, context: CurrentUserContext, filters: AuditLogFilter
    ) -> Iterator[str]:
        scope = self._resolve_scope(context, filters)

        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def flush() -> str:
            value = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            return value

        writer.writerow(_EXPORT_COLUMNS)
        yield flush()

        emitted = 0
        for row in self.repository.iter_for_export(
            scope, filters, max_rows=_EXPORT_MAX_ROWS
        ):
            writer.writerow(_export_row(row))
            yield flush()
            emitted += 1

        if emitted >= _EXPORT_MAX_ROWS:
            yield f"# truncated at {_EXPORT_MAX_ROWS} rows — narrow the date range\n"


def _export_row(row: AuditLogRead) -> list[str]:
    return [
        row.created_at.isoformat(),
        row.actor_email or "",
        row.actor_name or "",
        row.action,
        str(row.organization_id) if row.organization_id else "",
        row.organization_name or "",
        row.target_type or "",
        str(row.target_id) if row.target_id else "",
        row.target_label or "",
        json.dumps(row.changed_fields, separators=(",", ":"))
        if row.changed_fields
        else "",
        str(row.id),
    ]
