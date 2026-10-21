PLAYBOOK_EXTRACTION_QUEUE_NAME = "playbook_extraction"
PLAYBOOK_EXTRACTION_ACTOR_NAME = "playbook_extraction.process"

# Model calls are billed; a failed run is retried by a person, never automatically.
PLAYBOOK_EXTRACTION_MAX_RETRIES = 0
PLAYBOOK_EXTRACTION_TIME_LIMIT_MS = 25 * 60 * 1000
# A RUNNING row older than this belongs to a worker that died mid-run. A redelivered
# message may claim it again; younger rows are left to the worker processing them.
PLAYBOOK_EXTRACTION_STALE_AFTER_SECONDS = 30 * 60

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
DEFAULT_MAX_SESSIONS = 20
MAX_SESSIONS_LIMIT = 50
