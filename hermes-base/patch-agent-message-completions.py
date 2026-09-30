"""Capture completions at the pinned scheduler's fenced durable side-effect boundary."""

from pathlib import Path


def patch(source: str) -> str:
    marker = "# Agent Barn durable completion bridge"
    if marker in source:
        return source
    capture = '                output_file = save_job_output(job["id"], output)'
    suppress = "            should_deliver = bool(deliver_content.strip())"
    preflight = '        ("delivery", lambda: _preflight_check_delivery(job)),'
    if any(source.count(anchor) != 1 for anchor in (capture, suppress, preflight)):
        raise RuntimeError("Pinned Hermes scheduler changed: completion bridge anchors are not unique")
    # Native platforms never get credentials here, so the delivery preflight would block
    # every `deliver: slack:...` job before it runs; destination_for_origin polices targets.
    source = source.replace(
        preflight,
        '        ("delivery", lambda: None if os.environ.get("AGENTBARN_SCHEDULED_DELIVERY") == "1"'
        " else _preflight_check_delivery(job)),",
    )
    source = source.replace(
        capture,
        """                # Agent Barn durable completion bridge
                if os.environ.get("AGENTBARN_SCHEDULED_DELIVERY") == "1":
                    # Delivery is the newer side effect; it must never cost the job its saved output.
                    try:
                        from agentbarn_message import capture_completion
                        if success and not _is_interrupted(job["id"], execution_token):
                            capture_completion("hermes:" + str(execution_id), final_response, job.get("origin"), job.get("deliver"))
                    except Exception as exc:
                        print(f"[agentbarn-message] scheduled completion not captured ({type(exc).__name__})", flush=True)
"""
        + capture,
    )
    return source.replace(
        suppress,
        suppress
        + """
            if os.environ.get("AGENTBARN_SCHEDULED_DELIVERY") == "1":
                # The shared client owns delivery; native transports have no credentials.
                should_deliver = False""",
    )


if __name__ == "__main__":
    path = Path("/opt/hermes/cron/scheduler.py")
    path.write_text(patch(path.read_text()))
