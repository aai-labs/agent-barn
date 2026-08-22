"""Bridge the Agent Barn Communications protocol to a local runtime HTTP API."""

import json
import os
import time
import urllib.error
import urllib.request

COMMUNICATIONS_URL = os.environ["COMMUNICATIONS_URL"].rstrip("/")
COMMUNICATIONS_API_KEY = os.environ["COMMUNICATIONS_API_KEY"]
AGENT_ID = os.environ["AGENT_ID"]
RUNTIME_API_URL = os.environ["RUNTIME_API_URL"].rstrip("/")
RUNTIME_API_KEY = os.environ["RUNTIME_API_KEY"]
RUNTIME_MODEL = os.environ["RUNTIME_MODEL"]


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
        "X-AgentBarn-Communications-Version": "1",
        "Content-Type": "application/json",
    }


def run_delivery(delivery: dict) -> None:
    delivery_id = delivery["delivery_id"]
    envelope = delivery["envelope"]
    session_key = (
        f"connection:{delivery['connection_id']}:"
        f"{envelope['location']['id']}:{envelope['location'].get('thread_id') or 'root'}"
    )
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
    http_request(
        "POST",
        f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/{delivery_id}/complete",
        headers=communications_headers(),
        payload=completion,
    )


def main() -> None:
    while True:
        try:
            delivery = http_request(
                "POST",
                f"{COMMUNICATIONS_URL}/agents/{AGENT_ID}/deliveries/claim",
                headers=communications_headers(),
            )
            if delivery is None:
                time.sleep(0.5)
                continue
            run_delivery(delivery)
        except Exception as exc:
            print(f"[communications-adapter] {exc}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
