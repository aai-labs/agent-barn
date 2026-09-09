"""Capture completions at the pinned scheduler's fenced durable side-effect boundary."""

from pathlib import Path


def patch(source: str) -> str:
    marker = "# Agent Barn durable completion bridge"
    if marker in source:
        return source
    capture = '                output_file = save_job_output(job["id"], output)'
    suppress = "            should_deliver = bool(deliver_content.strip())"
    if source.count(capture) != 1 or source.count(suppress) != 1:
        raise RuntimeError("Pinned Hermes scheduler changed: completion bridge anchors are not unique")
    source = source.replace(
        capture,
        """                # Agent Barn durable completion bridge
                if os.environ.get("AGENTBARN_SCHEDULED_DELIVERY") == "1":
                    from agentbarn_message import capture_completion
                    if success and not _is_interrupted(job["id"], execution_token):
                        capture_completion("hermes:" + str(execution_id), final_response, job.get("origin"), job.get("deliver"))
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
