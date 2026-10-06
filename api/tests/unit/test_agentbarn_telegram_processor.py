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

    processed = processor.process_pending()

    # The first stays RECEIVED for the next pass; the second is still settled.
    assert processed == 2
    assert [call.args[0] for call in repository.settle_update.call_args_list] == [1, 2]
