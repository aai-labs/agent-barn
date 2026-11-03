PLAYBOOK_EXTRACTION_QUEUE_NAME = "playbook_extraction"
PLAYBOOK_EXTRACTION_ACTOR_NAME = "playbook_extraction.process"

# Model calls are billed; a failed run is retried by a person, never automatically.
PLAYBOOK_EXTRACTION_MAX_RETRIES = 0
PLAYBOOK_EXTRACTION_TIME_LIMIT_MS = 25 * 60 * 1000
# The time limit stops a live run before this, so a RUNNING row older than this belongs
# to a worker that died or was killed mid-run. Keep it longer than the time limit: a
# shorter window could fail a run that is still working.
PLAYBOOK_EXTRACTION_STALE_AFTER_SECONDS = 30 * 60
# A QUEUED row this old lost its message; the worker normally starts runs within seconds.
PLAYBOOK_EXTRACTION_QUEUED_STALE_AFTER_SECONDS = 60 * 60

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
DEFAULT_MAX_SESSIONS = 20
MAX_SESSIONS_LIMIT = 50
