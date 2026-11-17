# Anomaly detection

## Read when

Read before changing how Agents are checked for unusual activity: the Organization
opt-in, what counts as an Agent's normal and how it is learned, the scheduled check,
Anomaly records, the per-Agent override, or who may see any of it.

## Role in the system

An Organization may turn on checks that compare each of its Agents' activity with what
is normal for that Agent, learned from its own last 14 days. A check that sees something
unusual records an **Anomaly**, shown on the Agent's Anomalies tab. Detection is passive:
nobody is alerted and nothing is stopped.

This is the first slice of anomaly detection (AF-453, epic AF-198). It finds candidates
with statistics alone and calls no model. Later slices add off-hours signals, a decision
model that classifies candidates, alerts with acknowledge and resolve, and quarantine.

## Authorization

- Everything here needs the Organization Permissions `anomaly.read` (see Anomalies, the
  normal and the opt-in) or `anomaly.manage` (change the opt-in or an Agent's override).
  Only Owners and Admins hold them, and no Agent Access Role carries them: watching
  Agents is oversight of the Organization, so a Member who owns an Agent does not see its
  Anomalies. See the [RBAC brief](rbac/IMPLEMENTATION-BRIEF.md#agent-access-roles).
- Agent routes resolve the Agent through `AgentAuthorization.require_visible` before the
  Organization Permission, so an Agent the caller cannot see is `404` and a visible one
  without the Permission is `403`, as for `agent.size.manage`.
- The scheduled check is background work under the RBAC brief's exception: no router
  reaches it, and it takes Organizations and Agents from persisted rows.

## Opt-in

- `organization_anomaly_settings.enabled`, off by default (no row is off). Owners and
  Admins change it in **Settings → Unusual activity**.
- The setting says up front that checks may use an AI model provider and are billed to
  each Agent, so turning on classification later needs no second consent.
- Turning it off stops the checks and forgets how far they had read each Agent
  (`agent_anomaly_state`). Turning it back on makes the next check learn what the Agents
  did meanwhile rather than flag all of it as a first use. Anomalies already recorded stay.
- Each change records `organization.anomaly_detection.changed` in the security audit log.

## What is checked

Rates, per hour, against the Agent's own active hours in the last 14 days:

| Signal | Source |
| --- | --- |
| `LLM_TOKENS_PER_HOUR` | `cost_record.total_tokens`, without memory processing |
| `LLM_CALLS_PER_HOUR` | `cost_record` rows, without memory processing |
| `TOOL_CALLS_PER_HOUR` | `tool_call` rows |
| `TOOL_ERROR_RATE` | share of `tool_call` rows in `ERROR` |
| `WRITES_PER_HOUR` | `business_action` rows with `is_write` |

First use, not seen in the last 14 days:

| Signal | Subject |
| --- | --- |
| `NEW_TOOL` | `tool_call.tool_name` |
| `NEW_INTEGRATION` | `business_action.integration` |
| `NEW_INTEGRATION_ACTION` | `<integration> <verb>`, such as `crm delete` next to `crm read`. Not recorded when the integration itself is new: that is one `NEW_INTEGRATION`. |
| `NEW_DESTINATION` | a host read from tool call arguments (below) |

Hard caps, set per Agent, fire whatever the baseline: `LLM_TOKENS_CAP`, `LLM_CALLS_CAP`.

### Destinations

Destinations come from tool calls only; there is no egress proxy. The UI says they are
"seen in tool calls". Only the host is kept, never the URL or other arguments.

| Runtime | Tool | Field |
| --- | --- | --- |
| OpenClaw | `web_fetch` | `url` |
| OpenClaw | `browser` | `targetUrl`, else `url`, when `action` is `open` or `navigate` |
| OpenClaw | `exec` | `curl` and `wget` URLs in `command` |
| Hermes | `web_extract` | `urls` (list) |
| Hermes | `browser_navigate` | `url` |
| Hermes | `terminal` | `curl` and `wget` URLs in `command` |

Fields were checked against the tool definitions at the versions the images pin (OpenClaw
`2026.8.2`, Hermes `v2026.8.19`) and against recorded tool calls. Shell commands go through
the Business Action classifier's parsing (`business_value.service.shell_invocations`), so
runtime-wrapped and chained commands read the same way; only URLs with an `http` or
`https` scheme count, since a bare `example.com` cannot be told apart from an option value
like `-o out.json`.

Not seen: traffic from inside scripts and libraries, Hermes `browser_exec` and
`execute_code` (their URLs sit inside code), and `web_search`, which carries only a query.
Hermes after the pinned version replaces `browser_navigate` with `browser_exec`, so a Hermes
image bump stops browser destinations from being seen on Hermes.

## Learning what is normal

Pure functions in `api/domains/anomalies/detection.py`.

- An **active hour** is a UTC hour with at least one LLM call or tool call. Rates are
  judged over active hours only; an Agent idle most of the day would otherwise have a
  median and spread of zero and flag on any work. Quiet signals in an active hour count
  as zero.
- **Baseline**: the median and the median absolute deviation (scaled by 1.4826) of the
  hourly values. The spread is at least a per-signal minimum and 10% of the median, so a
  perfectly steady Agent tolerates small changes.
- **Threshold**: median + k × spread, k = 2.5 (high), 3.5 (normal) or 5 (low sensitivity),
  and never below a per-signal floor, so tiny numbers (0 → 3 calls) never flag.
- **Error rate** counts only hours with at least 10 tool calls, in the baseline and in the
  hour being checked.
- **Minimum history**: nothing is flagged until the Agent was active on at least 3
  different days in the window, for rates and first use alike. Hard caps apply straight
  away.
- The window slides: every check uses the 14 days before the hour it checks, and the
  hour being checked is not part of its own baseline. No time-of-day seasonality.

## The check

`AnomalyCheckService.run_checks`, run by the `anomaly-checks` CronJob every 15 minutes,
five minutes after each cost sync starts (`make run-anomaly-checks` locally).

- The checked hour ends two minutes before the run, because rows are stamped when
  inserted but seen only once committed. LLM figures stop at the last completed cost sync
  (they arrive up to about 30 minutes late), and are skipped entirely before any sync.
- Rates: an Anomaly starts when a check sees the value above the threshold. While later
  checks keep seeing it, the same row is kept up to date (`last_observed_at`, the highest
  observed value, the latest usual value and threshold); the first check that does not
  ends it (`ended_at`). A later deviation starts a new row. At most one ongoing Anomaly
  exists per Agent, signal and subject (`uq_agent_anomaly_ongoing`).
- First use: the check reads tool calls and Business Actions stored since its last
  cursor (`agent_anomaly_state`, by `created_at`, so late rows are read once). Each tool,
  integration, action and host is looked up in the Agent's ledger
  (`agent_activity_seen`); one not seen since 14 days before its use is recorded as an
  Anomaly that starts and ends at that use. The ledger then records the use.
- The first check of an Agent only fills its ledger from its last 14 days and flags no
  first use.
- Each Agent is checked on its own: one failing is logged, the rest still run and the Job
  succeeds, so it is not restarted to check every Agent again. The next run, 15 minutes
  later, retries the failed Agent. A run that cannot check at all (no database) fails.

## Anomaly records

`agent_anomaly` keeps the signal, the subject (first use) or none (rates), the observed
value, the usual value (none for caps and first use), the threshold, and when it started,
was last seen and ended. A later slice classifies candidates with a decision model; the
record already has `classification_state` (`STATISTICS_ONLY` until then),
`classification_category`, `classification_severity` and `classification` for it, so that
slice does not reshape the table. Data sent to a model provider then must be derived
features, not these records.

## Override

`agent_anomaly_override`: sensitivity (default normal) and optional hard caps on model
tokens and model calls per hour. Owners and Admins change it in the Normal behaviour
section of the Agent's Anomalies tab. Each change records `agent.anomaly_override.changed`
(the token cap is `max_llm_usage_per_hour` in the payload, since payload keys naming tokens
are refused). An unchanged save records nothing.

## API

| Route | Permission |
| --- | --- |
| `GET`/`PUT /organizations/{id}/anomaly-detection` | `anomaly.read` / `anomaly.manage` |
| `GET /organizations/{id}/agents/{agent_id}/anomalies` (newest first, paged) | `anomaly.read` |
| `GET /organizations/{id}/agents/{agent_id}/normal-behaviour` | `anomaly.read` |
| `PUT /organizations/{id}/agents/{agent_id}/anomaly-override` | `anomaly.manage` |

The normal-behaviour read works out the baseline exactly as the next check would: usual
values and thresholds at the Agent's sensitivity, and the tools, integrations, actions and
hosts it used in its last 14 days.

## Runtimes

Rates and first use of tools and integrations read runtime-neutral tables, filled the same
way for Hermes and OpenClaw. Destination parsing is per runtime (the table above) and is
tested with each runtime's argument shapes.

## Deliberately left for later

- **Confirmed Anomalies feeding back into the baseline.** The baseline is built from raw
  activity and ignores Anomaly records, so a deviation that lasts days becomes part of
  its own normal. Once classification (decision model) or a person (acknowledge/resolve)
  can confirm an Anomaly, the baseline queries should leave out the matching activity:
  those hours for rates, that tool, integration, action or host for first use. Anomalies
  dismissed as fine stay in. The record already carries what that filter needs: signal,
  subject, the hours it covers and a status the later slices can update.
- Off-hours and business-hours signals, classification, alerts, an Organization-wide
  Anomalies page, and quarantine.
- LLM spend per hour, which follows tokens per model closely.
- Pruning ledger entries older than the window; they already count as unseen.
