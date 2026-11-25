# Anomaly detection — change log

Status: Active
Epic: AF-198
Related context: [`../anomaly-detection.md`](../anomaly-detection.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered:
  - the platform decision model and `DecisionService.decide` (AF-449);
  - the Organization opt-in, which already tells Owners that checks may be billed to each Agent;
  - the scheduled statistics-only check: rates against each Agent's own last 14 days, first use of tools, integrations, actions and hosts, and hard caps on model tokens and calls;
  - Anomaly records; each new one is classified once by the decision model (kind, severity, how likely it is really unusual), billed to its Agent, and stays `STATISTICS_ONLY` if that call fails (AF-459);
  - the per-Agent override, and the Agent's Unusual activity tab for Owners and Admins, which shows each item's classification;
  - email alerts to Owners and Admins about newly flagged activity of `MEDIUM` severity or above that is not probably fine, or that could not be classified (AF-464).
- In transition: nothing.
- Next: acknowledge and resolve, and quarantine on critical (AF-465).
- Later: acknowledge and resolve, an Organization-wide Anomalies page, and quarantine (AF-465).
- Blockers: none.

## Changes

### 2026-11-25 — AF-464

- Delivered: Owners and Admins (whoever `anomaly.read` reaches) are emailed when a check newly flags activity worth a look for one of their Agents: classified `MEDIUM` or above and not probably fine, or not classified. One email per recipient per check, naming the Agent, what was flagged and how it was classified, with a link to the Unusual activity tab. Ongoing activity does not alert again.
- Changed: the Event `agent.anomaly.flagged`, recorded in the check's transaction and enqueued after classification, and its handler `AnomalyAlertEmailHandler`; table `anomaly_alert_email_receipt` (migration `2180817c8927`); `CheckWrites.record_flagged`; `OrganizationLookupService.recipients_with_permission`; `AgentService.agent_name`; `EmailService.send_anomaly_alert_email` and its template.
- Follow-up: AF-465 can reuse the Event to quarantine on `CRITICAL`; a failed classification alerts about five minutes late, after the handler's wait for classification.

### 2026-11-24 — AF-459

- Delivered: each Anomaly that starts in a check is classified once by the platform decision model, in one call per Agent billed to its own LiteLLM key, and the Unusual activity tab shows its kind, severity and "Probably fine" when the model thinks it is likely ordinary. A failed call (including a spent limit) leaves it as the statistics flagged it, with no retry.
- Changed: `agent_anomaly` classification fields are now filled (no migration); `GET /anomalies` returns `classification`; `CheckWrites.open_or_update` and `record_first_use` return the started Anomaly's id; `AgentService.agent_role` and `ConversationService.recent_inbound_texts` for background reads. What reaches the provider: derived features, never a destination's host, plus the Agent's role and its latest inbound messages after cleaning, which also removes every held-back destination host (after whole links, emails and secrets, so it cannot split one) and IP addresses, and cleans at most 1,200 characters per message in linear time (see the feature doc).
- Follow-up: alerts (AF-464) can rely on `classification_category` and `classification_severity`, and must treat `STATISTICS_ONLY` as "not classified" rather than "harmless".

### 2026-11-23 — AF-453 — [#387](https://github.com/aai-labs/agent-barn/pull/387)

- Delivered: Agents of an Organization that opts in are checked every 15 minutes, and what is unusual for each is recorded as an Anomaly and shown on its Unusual activity tab. Nothing is alerted or stopped.
- Changed: tables `organization_anomaly_settings`, `agent_anomaly_override`, `agent_anomaly`, `agent_activity_seen` and `agent_anomaly_state` (migration `92996d692c89`); the Permissions `anomaly.read` and `anomaly.manage`; two audit Events; the `/anomaly-detection`, `/anomalies`, `/normal-behaviour` and `/anomaly-override` routes; the `anomaly-checks` CronJob and Compose service; the Settings section and the Agent tab.
- Follow-up: classification can fill the `classification_*` fields on `agent_anomaly` without reshaping the table. What it sends to a model provider must be derived features, not these records.
