# Anomaly detection — change log

Status: Active
Epic: AF-198
Related context: [`../anomaly-detection.md`](../anomaly-detection.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered:
  - the platform decision model and `DecisionService.decide` (AF-449), which nothing in anomaly detection calls yet;
  - the Organization opt-in, which already tells Owners that checks may be billed to each Agent;
  - the scheduled statistics-only check: rates against each Agent's own last 14 days, first use of tools, integrations, actions and hosts, and hard caps on model tokens and calls;
  - Anomaly records, with `classification_state` `STATISTICS_ONLY` and empty classification fields;
  - the per-Agent override, and the Agent's Unusual activity tab for Owners and Admins.
- In transition: nothing.
- Next: classification of candidates with the decision model (AF-459).
- Later: alerts with acknowledge and resolve, an Organization-wide Anomalies page, and quarantine.
- Blockers: none.

## Changes

### 2026-11-23 — AF-453 — [#387](https://github.com/aai-labs/agent-barn/pull/387)

- Delivered: Agents of an Organization that opts in are checked every 15 minutes, and what is unusual for each is recorded as an Anomaly and shown on its Unusual activity tab. Nothing is alerted or stopped.
- Changed: tables `organization_anomaly_settings`, `agent_anomaly_override`, `agent_anomaly`, `agent_activity_seen` and `agent_anomaly_state` (migration `92996d692c89`); the Permissions `anomaly.read` and `anomaly.manage`; two audit Events; the `/anomaly-detection`, `/anomalies`, `/normal-behaviour` and `/anomaly-override` routes; the `anomaly-checks` CronJob and Compose service; the Settings section and the Agent tab.
- Follow-up: classification can fill the `classification_*` fields on `agent_anomaly` without reshaping the table. What it sends to a model provider must be derived features, not these records.
