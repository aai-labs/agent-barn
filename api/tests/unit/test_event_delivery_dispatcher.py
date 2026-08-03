from unittest.mock import Mock
from uuid import uuid7

from api.domains.events.dispatch import EventDeliveryDispatcher


def test_dispatcher_immediate_enqueue_failure_does_not_raise():
    outbox_repository = Mock()
    transport = Mock()
    transport.enqueue.side_effect = RuntimeError("redis unavailable")
    dispatcher = EventDeliveryDispatcher(transport=transport, outbox_repository=outbox_repository)
    delivery_id = uuid7()

    dispatcher.enqueue_immediate([delivery_id])

    transport.enqueue.assert_called_once_with(delivery_id, metadata={"source": "immediate"})
    outbox_repository.mark_delivery_enqueued.assert_not_called()


def test_dispatcher_marks_delivery_enqueued_after_immediate_publish():
    outbox_repository = Mock()
    transport = Mock()
    dispatcher = EventDeliveryDispatcher(transport=transport, outbox_repository=outbox_repository)
    delivery_id = uuid7()

    dispatcher.enqueue_immediate([delivery_id])

    transport.enqueue.assert_called_once_with(delivery_id, metadata={"source": "immediate"})
    outbox_repository.mark_delivery_enqueued.assert_called_once_with(delivery_id)
