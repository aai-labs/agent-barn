from api.domains.agents.provisioning_errors import normalize_agent_provisioning_error

_POD_REASON_MESSAGES: dict[str, str] = {
    "CrashLoopBackOff": "Agent is crashing repeatedly on startup. Check the agent logs for details.",
    "OOMKilled": "Agent was killed — it ran out of memory.",
    "ImagePullBackOff": "Failed to pull the agent image. Check that the image registry is accessible and pull credentials are configured.",
    "ErrImagePull": "Failed to pull the agent image. Check that the image exists and the registry is reachable.",
    "CreateContainerConfigError": "Container configuration error — a secret or environment variable may be missing.",
    "CreateContainerError": "Failed to create the container. Check the pod configuration.",
    "Error": "Agent exited with an error.",
    "Completed": "Agent process exited unexpectedly.",
}


def friendly_pod_reason(raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw.startswith("exit code "):
        return f"Agent exited unexpectedly ({raw})."
    return _POD_REASON_MESSAGES.get(raw, raw)


def friendly_k8s_error(exc: Exception) -> str:
    """One-line sanitized, parsed rendering of a provisioning failure."""
    return normalize_agent_provisioning_error(exc).display_message
