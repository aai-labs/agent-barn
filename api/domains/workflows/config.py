"""Workflow-owned policy defaults; future per-Agent settings belong in this module."""

# A step runs as a full Agent session (tools, integrations), so it gets the Agent's chat turn budget.
ATTEMPT_TIMEOUT_SECONDS = 900
MAX_CONTEXT_BYTES = 64_000
HISTORY_RETENTION_DAYS = 90
# An attempt the Agent has not accepted after this long is reported as an unresponsive Agent.
DISPATCH_GRACE_SECONDS = 60
