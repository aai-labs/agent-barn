from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from api.domains.communications.agentbarn_telegram_repository import (
    AgentBarnTelegramRepository,
    LinkTokenConsumption,
    LinkTokenOutcome,
)

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _race() -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception("uq_agentbarn_telegram_link_active_user"))


def _consume(repository: AgentBarnTelegramRepository) -> LinkTokenConsumption:
    return repository.consume_link_token("hash", telegram_user_id=1, telegram_username=None, now=_NOW)


def test_a_lost_first_link_race_is_retried_once() -> None:
    repository = AgentBarnTelegramRepository(MagicMock())
    linked = LinkTokenConsumption(LinkTokenOutcome.LINKED)

    with patch.object(repository, "_consume", side_effect=[_race(), linked]) as consume:
        result = _consume(repository)

    assert result is linked
    assert consume.call_count == 2


def test_a_link_that_keeps_conflicting_is_not_retried_forever() -> None:
    repository = AgentBarnTelegramRepository(MagicMock())

    with patch.object(repository, "_consume", side_effect=[_race(), _race()]) as consume:
        with pytest.raises(IntegrityError):
            _consume(repository)

    assert consume.call_count == 2
