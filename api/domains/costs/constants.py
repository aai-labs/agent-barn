# LiteLLM's /spend/logs/v2 rejects a bare date with HTTP 400; it wants a full timestamp.
LITELLM_SPEND_LOG_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Rows arrive in the spend log slightly after the call they describe, so each sync
# re-reads the tail of the previous window rather than resuming exactly where it
# stopped. Re-reading is safe: the upsert is keyed on request_id.
COST_SYNC_WATERMARK_OVERLAP_SECONDS = 3600

# LiteLLM caps page_size at 1000.
COST_SYNC_PAGE_SIZE = 1000

# Must stay below the CronJob's schedule interval (900s). The job runs under
# concurrencyPolicy: Forbid, so a run that outlives its window does not overlap —
# it silently costs the next tick instead.
COST_SYNC_MAX_RUNTIME_SECONDS = 600

# OpenRouter's /generation endpoint held 18 req/s across 260 requests with zero 429s
# during the AF-281 benchmark. Eight keeps a comfortable margin under that.
COST_HEAL_CONCURRENCY = 8
COST_HEAL_BATCH_SIZE = 500
