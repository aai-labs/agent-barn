from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramUpdateProcessor
from api.domains.communications.models import AgentBarnTelegramUpdate


def _group_message(update_id: int) -> AgentBarnTelegramUpdate:
    return AgentBarnTelegramUpdate(
        update_id=update_id,
        payload={"message": {"from": {"id": 1, "is_bot": False}, "chat": {"id": -5, "type": "group"}}},
    )


def test_one_failing_update_does_not_hold_up_the_rest() -> None:
    repository = Mock()
    repository.received_updates.return_value = [_group_message(1), _group_message(2)]
    repository.settle_update.side_effect = [RuntimeError("database blip"), None]
    processor = AgentBarnTelegramUpdateProcessor(
        config=cast(Config, SimpleNamespace(web_app_url="https://app.agentbarn.test")),
        repository=repository,
        links=Mock(),
        authorization=Mock(),
        bot=Mock(),
    )

    repository.record_processing_failure.return_value = 1
    processed = processor.process_pending()

    # The first stays RECEIVED and waits out a backoff, so the next pass moves on
    # past it rather than retrying it at once; the second is still settled.
    assert processed == 2
    assert repository.record_processing_failure.call_args.args[0] == 1
    assert repository.record_processing_failure.call_args.kwargs["retry_at"] is not None
    assert [call.args[0] for call in repository.settle_update.call_args_list] == [1, 2]
