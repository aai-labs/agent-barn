from uuid import UUID, uuid4


def test_event_delivery_actor_delegates_to_domain_handler(monkeypatch):
    import api.worker_app as worker_app

    calls: list[UUID] = []
    monkeypatch.setattr(worker_app.events_worker, "process_event_delivery", calls.append)
    delivery_id = uuid4()

    worker_app.event_delivery_actor.fn(str(delivery_id), {"source": "test"})

    assert calls == [delivery_id]


def test_retry_exhausted_actor_delegates_to_domain_handler_with_parsed_retries(monkeypatch):
    import api.worker_app as worker_app

    calls: list[tuple[dict, int | None]] = []
    monkeypatch.setattr(
        worker_app.events_worker,
        "handle_retry_exhausted",
        lambda message, *, retries: calls.append((message, retries)),
    )
    message = {"args": [str(uuid4()), {"source": "test"}]}

    worker_app.event_delivery_retry_exhausted.fn(message, {"retries": 3})

    assert calls == [(message, 3)]
