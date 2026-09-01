# Inbound email reaches Agent Barn through a Cloudflare Email Worker

Status: Accepted
Date: 2026-08-31
Origin: AF-276 Email communication platform

A Cloudflare Email Routing rule can deliver only to a verified destination address or to a Worker; there is no native "POST this message to my HTTPS endpoint" destination. Agent Barn therefore ships a small Email Worker that parses the raw MIME message and posts a compact JSON payload to the Communications gateway, because that is the only programmatic destination Email Routing can reach.

## Considered alternatives

- **Forward to a real mailbox and poll it over IMAP.** Removes the Worker and the second deployment path, but adds a mailbox provider, stored IMAP credentials, polling latency, and a MIME parser in the API rather than at the edge. It trades roughly fifty lines of JavaScript for a new credential and a new external dependency.
- **Run our own SMTP server and point MX at it.** Maximum control and by far the largest operational surface: an internet-facing SMTP endpoint makes spam handling, TLS, abuse, and deliverability reputation our problem, none of which the product needs to own.
- **A third-party inbound-parse provider** (SendGrid Inbound Parse, Mailgun Routes, Postmark). These offer the webhook primitive natively and would remove the Worker entirely, but add a second email vendor with its own billing and DNS alongside the Cloudflare account already used for Email Sending.

## Consequences

The Worker runs on Cloudflare's edge rather than in the cluster: no pod, no Helm chart, no namespace quota, and no change to the Communications deployment. It authenticates to the gateway with a per-environment shared bearer secret rather than a per-Connection credential, because it is addressed by mailbox and knows only the recipient address, never a Connection id.

The Worker is deliberately thin — parse, truncate, forward. Every admission decision (sender policy, automated-mail guards, threading, length bounds) stays in the Python Platform Plugin, which is covered by tests. This matters because a new top-level `workers/` directory triggers no job in `ci.yml`, whose change detection covers only `api`, `ui`, `hermes`, and `openclaw`.

Deployment is a manual `wrangler deploy` outside the Helm and GitHub Actions flow. The running Worker can therefore drift from the committed source with nothing to detect it, and a revert of a Worker change does not revert the deployed Worker. Automating this needs a Cloudflare API token scoped to `Workers Scripts: Edit`; the existing `CLOUDFLARE_API_TOKEN` is scoped to `Email Sending: Edit` and broadening it would widen the blast radius of rotating it.

The Worker must not read `Authentication-Results`. Mail delivered to a Worker carries no such header and an `ARC-Authentication-Results` of only `arc=none` (cloudflare/workerd#6740), so a check there would silently pass everything. Cloudflare's MX already rejects mail failing the sender's DMARC policy before the Worker runs, and sender trust beyond that comes from the Connection's allowlist.

## Revisit when

Cloudflare adds an HTTPS destination to Email Routing, or the Worker starts accumulating logic that wants test coverage. Either removes the main reason this record exists.
