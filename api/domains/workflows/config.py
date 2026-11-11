"""Workflow-owned policy defaults; future per-Agent settings belong in this module."""

# A step runs as a full Agent session (tools, integrations), so it gets the Agent's chat turn budget.
ATTEMPT_TIMEOUT_SECONDS = 900
MAX_CONTEXT_BYTES = 64_000
HISTORY_RETENTION_DAYS = 90
# An attempt the Agent has not accepted after this long is reported as an unresponsive Agent.
DISPATCH_GRACE_SECONDS = 60
# A live approval closes before Hermes's own 300-second approval timeout denies the command.
APPROVAL_LIVE_SECONDS = 270
# Declines of one step before the run blocks for a person instead of asking again.
MAX_DECLINES_PER_STEP = 3
