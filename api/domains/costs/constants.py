from decimal import Decimal

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

# Fixed dollar bands for the cost-per-call histogram. Fixed rather than derived from
# the data, so the shape can be compared between two filters and two organizations.
# The band above the last bound is open-ended.
COST_HISTOGRAM_BOUNDS = (
    Decimal("0.0001"),
    Decimal("0.001"),
    Decimal("0.005"),
    Decimal("0.01"),
    Decimal("0.05"),
    Decimal("0.1"),
    Decimal("0.5"),
    Decimal(1),
)

# A line per agent stops being readable long before an organization stops having
# agents, so the spend-by-agent chart shows only the biggest spenders.
TOP_AGENTS_IN_SERIES = 8
