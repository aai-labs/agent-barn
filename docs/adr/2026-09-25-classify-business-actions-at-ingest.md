# Classify Business Actions at Ingest and store them in PostgreSQL

Status: Accepted
Date: 2026-09-25
Origin: AF-344

Agent Barn derives Business Actions on the server. It classifies the aai-cli commands inside stored `terminal` (Hermes) and `exec` (OpenClaw) Tool Calls against a code-owned catalogue, and writes the result to a PostgreSQL `business_action` table in the same Ingest transaction as the Tool Call. Doing this at Ingest covers both runtimes at once, needs no runtime image or plugin release, and leaves the runtime digest unchanged. Storing the rows next to the Tool Calls they come from keeps them under the same Organization and Agent tenancy that Agent Access already enforces.

Considered alternatives:

- PostHog: its self-hosted Kubernetes deployment no longer accepts new installs ("New deployments of PostHog's paid open source product using Kubernetes are no longer supported"), and the self-hosted stack runs Kafka and ClickHouse.
- OpenPanel: it is licensed AGPL-3.0.
- Neither product respects Agent Access, so reports built on them would bypass the Agent-level authorization every other Agent surface follows.

Consequences:

- The catalogue is code-owned and outside `aai_cli_skills/bundled/`. A catalogue change needs a deploy, but no migration (`outcome_type` is a plain VARCHAR) and no runtime update. The operator backfill re-maps rows already stored.
- Both runtime images build aai-cli unpinned from its default branch. The binary has no `--version`, so its source commit cannot be recovered. Commands can therefore drift from the bundled references, and anything the catalogue does not know is stored as unclassified rather than guessed.

Revisit when an analytics product can enforce Agent Access, or when the runtimes pin aai-cli and report exit status in Tool Call telemetry.
