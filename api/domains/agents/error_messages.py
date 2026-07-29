import json

_K8S_STATUS_MESSAGES: dict[int, str] = {
    403: "Permission denied — the API server rejected the request. Check the service account RBAC configuration.",
    404: "Kubernetes namespace or resource not found. Check your cluster configuration.",
    409: "A conflicting resource already exists in the cluster. Try stopping the agent first.",
    422: "Invalid resource configuration — the cluster rejected the manifest.",
}

_TERMINAL_LLM_ERRORS: dict[int, str] = {
    401: "LLM API key is invalid or expired. Check your API key configuration.",
    402: "OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits.",
    403: "LLM API access denied. Check your account permissions.",
}

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
    body = getattr(exc, "body", None)
    status_code = getattr(exc, "status", None)
    if body:
        try:
            parsed = json.loads(body) if isinstance(body, (str, bytes)) else body
            msg = parsed.get("message") or parsed.get("reason") or ""
            if msg:
                friendly = _K8S_STATUS_MESSAGES.get(status_code) if isinstance(status_code, int) else None
                return f"{friendly} ({msg})" if friendly else msg
        except Exception:
            pass
    if status_code and status_code in _K8S_STATUS_MESSAGES:
        return _K8S_STATUS_MESSAGES[status_code]
    raw = str(exc)
    if "ImagePull" in raw or "image" in raw.lower():
        return _POD_REASON_MESSAGES["ImagePullBackOff"]
    if "Forbidden" in raw or "403" in raw:
        return _K8S_STATUS_MESSAGES[403]
    if "not found" in raw.lower() or "404" in raw:
        return _K8S_STATUS_MESSAGES[404]
    return raw[:500]


def classify_terminal_llm_error(status_code: int) -> str | None:
    return _TERMINAL_LLM_ERRORS.get(status_code)


def build_clean_error_body(status_code: int, message: str) -> str:
    return json.dumps({"error": {"message": message, "type": None, "param": None, "code": str(status_code)}})
