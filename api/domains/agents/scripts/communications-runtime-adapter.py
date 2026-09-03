"""Bridge the Agent Barn Communications protocol to a local runtime HTTP API."""

import json
import os
import threading
import time
import urllib.error
import urllib.request

COMMUNICATIONS_URL = os.environ["COMMUNICATIONS_URL"].rstrip("/")
COMMUNICATIONS_API_KEY = os.environ["COMMUNICATIONS_API_KEY"]
COMMUNICATIONS_PROTOCOL_VERSION = os.environ.get("COMMUNICATIONS_PROTOCOL_VERSION", "2")
AGENT_ID = os.environ["AGENT_ID"]
RUNTIME_API_URL = os.environ["RUNTIME_API_URL"].rstrip("/")
RUNTIME_API_KEY = os.environ["RUNTIME_API_KEY"]
RUNTIME_MODEL = os.environ["RUNTIME_MODEL"]
CLAIM_SAFETY_POLL_INTERVAL_SECONDS = 5


class InFlightDelivery:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._delivery_id: str | None = None
        self._session_key: str | None = None
        self._cancel_requested = False

    def begin(self, delivery_id: str, session_key: str) -> None:
        with self._lock:
            self._delivery_id = delivery_id
            self._session_key = session_key
            self._cancel_requested = False

    def clear(self, delivery_id: str) -> None:
        with self._lock:
            if self._delivery_id != delivery_id:
                return
            self._delivery_id = None
            self._session_key = None
            self._cancel_requested = False

    def request_cancel(self, delivery_id: str) -> str | None:
        with self._lock:
            if self._delivery_id != delivery_id:
                return None
            self._cancel_requested = True
            return self._session_key

    def is_cancel_requested(self, delivery_id: str) -> bool:
        with self._lock:
            return self._delivery_id == delivery_id and self._cancel_requested


IN_FLIGHT = InFlightDelivery()


def http_request(method: str, url: str, *, headers: dict[str, str], payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=900) as response:
            if response.status == 204:
                return None
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def communications_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {COMMUNICATIONS_API_KEY}",
        "X-AgentBarn-Communications-Version": COMMUNICATIONS_PROTOCOL_VERSION,
        "Content-Type": "application/json",
    }


def request_local_cancel(delivery_id: str) -> None:
    # Neither pinned runtime exposes a proven abort handle for the OpenAI-style
    # chat-completions request. Marking the in-flight turn is still immediate:
    # its eventual result is suppressed locally and rejected atomically by the
    # durable source-delivery check in Communications.
    IN_FLIGHT.request_cancel(delivery_id)


def run_delivery(delivery: dict) -> None:
    delivery_id = delivery["delivery_id"]
    envelope = delivery["envelope"]
    session_key = (
        f"connection:{delivery['connection_id']}:"
        f"{envelope['location']['id']}:{envelope['location'].get('thread_id') or 'root'}"
    )
    IN_FLIGHT.begin(delivery_id, session_key)
    try:
        result = http_request(
            "POST",
            f"{RUNTIME_API_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {RUNTIME_API_KEY}",
                "Content-Type": "application/json",
                "X-OpenClaw-Session-Key": session_key,
                "X-Hermes-Session-Key": session_key,
                "Idempotency-Key": delivery_id,
            },
            payload={
                "model": RUNTIME_MODEL,
                "stream": False,
                "user": session_key,
                "messages": [{"role": "user", "content": envelope.get("text", "")}],
            },
        )
        if IN_FLIGHT.is_cancel_requested(delivery_id):
            completion = {
                "succeeded": False,
                "error_code": "CANCELLED",
                "error_message": "Cancelled by user",
            }
        else:
            reply = result["choices"][0]["message"]["content"]
            http_request(
                "POST",
                f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/replies",
                headers=communications_headers(),
                payload={"idempotency_key": delivery_id, "text": reply},
            )
            completion = {"succeeded": True}
    except Exception as exc:
        completion = {
            "succeeded": False,
            "error_code": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
    try:
        http_request(
            "POST",
            f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/complete",
            headers=communications_headers(),
            payload=completion,
        )
    finally:
        IN_FLIGHT.clear(delivery_id)


class DeliveryWorker:
    """Drain durable claims on signals, with a bounded lost-wakeup fallback."""

    def __init__(self) -> None:
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="communications-delivery", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while True:
            # Redis is only a wakeup optimization. A publish can fail after
            # PostgreSQL commits, so periodically retry the durable claim even
            # when the control stream has not delivered a signal.
            self._wake.wait(timeout=CLAIM_SAFETY_POLL_INTERVAL_SECONDS)
            self._wake.clear()
            try:
                self._drain()
            except Exception as exc:
                print(f"[communications-adapter] delivery worker: {exc}", flush=True)
                time.sleep(2)
                self._wake.set()

    def _drain(self) -> None:
        while True:
            delivery = http_request(
                "POST",
                f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/claim",
                headers=communications_headers(),
            )
            if delivery is None:
                return
            run_delivery(delivery)


def consume_control_stream(worker: DeliveryWorker) -> None:
    req = urllib.request.Request(
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/control",
        method="GET",
        headers={
            "Authorization": f"Bearer {COMMUNICATIONS_API_KEY}",
            "X-AgentBarn-Communications-Version": COMMUNICATIONS_PROTOCOL_VERSION,
            "Accept": "text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        for raw_line in response:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if event.get("type") == "delivery_available":
                worker.wake()
            elif event.get("type") == "delivery_cancelled" and event.get("delivery_id"):
                request_local_cancel(event["delivery_id"])


def main() -> None:
    worker = DeliveryWorker()
    worker.start()
    reconnect_delay = 1
    while True:
        try:
            consume_control_stream(worker)
            print("[communications-adapter] control stream closed; reconnecting", flush=True)
        except Exception as exc:
            print(f"[communications-adapter] control stream: {exc}", flush=True)
        time.sleep(reconnect_delay)
        reconnect_delay = min(15, reconnect_delay * 2)


if __name__ == "__main__":
    main()
