from uuid import UUID, uuid4

import pytest

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


class FakeInjector:
    def __init__(self, repository, *, registry_error: Exception | None = None):
        self.repository = repository
        self.registry_error = registry_error

    def get(self, interface):
        from api.domains.events.handlers import EventHandlerRegistry
        from api.domains.events.repository import OutboxMessageRepository

        if interface is OutboxMessageRepository:
            return self.repository
        if interface is EventHandlerRegistry:
            if self.registry_error is not None:
                raise self.registry_error
            return EventHandlerRegistry()
        raise AssertionError(f"unexpected dependency {interface!r}")


@pytest.fixture
def worker_with_injector_factory(monkeypatch):
    """Reload the worker module with a patched injector factory, and reload it clean afterwards."""
    import importlib

    from api.core import utils
    from api.domains.events import worker

    def install(factory):
        monkeypatch.setattr(utils, "create_injector", factory)
        importlib.reload(worker)
        return worker

    try:
        yield install
    finally:
        monkeypatch.undo()
        importlib.reload(worker)


def test_worker_builds_one_injector_per_process_and_none_at_import(worker_with_injector_factory):
    created: list[FakeInjector] = []
    repository = FakeRepository()

    def counting_create_injector():
        created.append(FakeInjector(repository))
        return created[-1]

    worker = worker_with_injector_factory(counting_create_injector)
    assert created == [], "importing the worker module must not build an injector"

    processors = [worker._processor() for _ in range(3)]
    repositories = [worker._repository() for _ in range(2)]

    assert len(created) == 1
    assert all(processor.repository is repository for processor in processors)
    assert all(candidate is repository for candidate in repositories)


def test_processor_propagates_handler_registry_resolution_failure(worker_with_injector_factory):
    registry_error = RuntimeError("registry wiring failed")
    worker = worker_with_injector_factory(lambda: FakeInjector(FakeRepository(), registry_error=registry_error))

    with pytest.raises(RuntimeError) as raised:
        worker._processor()

    assert raised.value is registry_error
