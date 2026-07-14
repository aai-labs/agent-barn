"""Unit tests for AuditLogService: failure isolation, redaction, read-suppression, and
changed-field diffing. These run without a database (the repository is mocked)."""

from unittest.mock import Mock
from uuid import uuid7

from hamcrest import assert_that, equal_to, is_

from api.domains.audit_logs.models import AuditAction, AuditLog
from api.domains.audit_logs.service import (
    REDACTED,
    AuditLogService,
    diff_changed_fields,
    redact_changed_fields,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.users.models import User


def _service(repository=None) -> AuditLogService:
    return AuditLogService(repository=repository or Mock())


def _context(is_superuser: bool = False) -> CurrentUserContext:
    user = User(
        id=uuid7(),
        email="actor@example.com",
        full_name="Actor Name",
        hashed_password="x",
        is_superuser=is_superuser,
    )
    return CurrentUserContext(user=user)


# --- failure isolation ---------------------------------------------------------


def test_record_never_raises_when_repository_fails():
    repo = Mock()
    repo.save.side_effect = RuntimeError("db down")
    service = _service(repo)

    # Must not propagate — an audit failure can't be allowed to fail the user's request.
    service.record(action=AuditAction.AGENT_CREATE, context=_context())


def test_record_snapshots_actor_from_context():
    repo = Mock()
    service = _service(repo)
    context = _context(is_superuser=True)

    service.record(action=AuditAction.AGENT_CREATE, context=context)

    saved: AuditLog = repo.save.call_args.args[0]
    assert_that(saved.actor_user_id, equal_to(context.user.id))
    assert_that(saved.actor_email, equal_to("actor@example.com"))
    assert_that(saved.actor_name, equal_to("Actor Name"))
    assert_that(saved.is_superuser_actor, is_(True))
    assert_that(saved.action, equal_to("agent.create"))


def test_record_uses_explicit_actor_without_context():
    repo = Mock()
    service = _service(repo)
    actor_id = uuid7()

    service.record(
        action=AuditAction.AUTH_LOGIN_FAILED,
        actor_user_id=actor_id,
        actor_email="who@example.com",
        organization_id=None,
    )

    saved: AuditLog = repo.save.call_args.args[0]
    assert_that(saved.actor_user_id, equal_to(actor_id))
    assert_that(saved.actor_email, equal_to("who@example.com"))
    assert_that(saved.organization_id, is_(None))


# --- redaction (default-deny) --------------------------------------------------


def test_redact_changed_fields_default_deny():
    result = redact_changed_fields(
        {"name": "new", "slack_bot_token": "xoxb-secret"}, {"name"}
    )
    assert_that(result["name"], equal_to("new"))
    assert_that(result["slack_bot_token"], equal_to(REDACTED))


def test_diff_changed_fields_records_old_new_for_allowlisted_only():
    before = Mock()
    before.name = "old-name"
    before.slack_bot_token = "xoxb-old"

    diff = diff_changed_fields(
        before,
        {"name": "new-name", "slack_bot_token": "xoxb-new"},
        {"name"},
    )

    assert_that(diff["name"], equal_to({"old": "old-name", "new": "new-name"}))
    # Sensitive field: the change is recorded but both values are redacted.
    assert_that(diff["slack_bot_token"], equal_to({"old": REDACTED, "new": REDACTED}))


def test_diff_changed_fields_skips_unchanged():
    before = Mock()
    before.name = "same"
    diff = diff_changed_fields(before, {"name": "same"}, {"name"})
    assert_that(diff, equal_to({}))


# --- read suppression ----------------------------------------------------------


def test_repeated_reads_are_suppressed_within_window():
    repo = Mock()
    service = _service(repo)
    actor_id = uuid7()
    target_id = uuid7()

    for _ in range(3):
        service.record(
            action=AuditAction.AGENT_VIEW,
            actor_user_id=actor_id,
            target_id=target_id,
        )

    # Only the first identical read is persisted.
    assert_that(repo.save.call_count, equal_to(1))


def test_reads_on_distinct_targets_are_not_suppressed():
    repo = Mock()
    service = _service(repo)
    actor_id = uuid7()

    service.record(
        action=AuditAction.AGENT_VIEW, actor_user_id=actor_id, target_id=uuid7()
    )
    service.record(
        action=AuditAction.AGENT_VIEW, actor_user_id=actor_id, target_id=uuid7()
    )

    assert_that(repo.save.call_count, equal_to(2))


def test_mutations_are_never_suppressed():
    repo = Mock()
    service = _service(repo)
    actor_id = uuid7()
    target_id = uuid7()

    for _ in range(3):
        service.record(
            action=AuditAction.AGENT_UPDATE,
            actor_user_id=actor_id,
            target_id=target_id,
        )

    assert_that(repo.save.call_count, equal_to(3))
