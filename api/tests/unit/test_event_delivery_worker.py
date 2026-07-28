from uuid import UUID, uuid4

from api.domains.events.models import EventDeliveryDeadLetterReason


class FakeProcessor:
    def __init__(self):
        self.processed: list[UUID] = []

    def process(self, delivery_id: UUID) -> bool:
        self.processed.append(delivery_id)
        return True


class FakeRepository:
    def __init__(self):
        self.dead_lettered = []

    def mark_delivery_dead_lettered(self, delivery_id, *, reason, error):
        self.dead_lettered.append((delivery_id, reason, error))


def test_process_event_delivery_invokes_processor_with_delivery_id(monkeypatch):
    from api.domains.events import worker

    processor = FakeProcessor()
    monkeypatch.setattr(worker, "_processor", lambda: processor)
    delivery_id = uuid4()

    result = worker.process_event_delivery(delivery_id)

    assert result is True
    assert processor.processed == [delivery_id]


def test_handle_retry_exhausted_marks_delivery_dead_lettered(monkeypatch):
    from api.domains.events import worker

    repository = FakeRepository()
    monkeypatch.setattr(worker, "_repository", lambda: repository)
    delivery_id = uuid4()

    worker.handle_retry_exhausted({"args": [str(delivery_id), {"source": "test"}]}, retries=3)

    assert repository.dead_lettered == [
        (
            delivery_id,
            EventDeliveryDeadLetterReason.RETRY_EXHAUSTED,
            f"Dramatiq retries exhausted for Event Delivery {delivery_id} after 3 retries",
        )
    ]


def test_handle_retry_exhausted_without_delivery_id_is_a_noop(monkeypatch):
    from api.domains.events import worker

    repository = FakeRepository()
    monkeypatch.setattr(worker, "_repository", lambda: repository)

    worker.handle_retry_exhausted({"args": []}, retries=None)

    assert repository.dead_lettered == []
