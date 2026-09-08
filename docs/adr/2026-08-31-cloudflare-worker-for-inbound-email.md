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

The Worker is deliberately thin — parse, truncate, forward. Every admission decision (sender policy, automated-mail guards, threading, length bounds) stays in the Python Platform Plugin, which is covered by tests.

Deployment runs through the existing pipeline rather than by hand. `ci.yml` and `deploy.yml` both call a `worker.yml` reusable workflow, the same shape as `ui.yml`: pull requests bundle it with `wrangler deploy --dry-run`, which needs no Cloudflare credentials and therefore works on forks, and merges to `staging`/`main` publish it — but only when `workers/**` actually changed, so rollback history is not consumed by unrelated merges. It publishes *after* the cluster deploy, because the Worker posts into the Communications service and the cluster must already hold the matching secret.

`EMAIL_INBOUND_SECRET` is written to the Worker by the same run that writes it into the cluster Secret, from one GitHub secret. That removes the class of failure where the two drift apart and every inbound message answers `401`.

This needs a Cloudflare token scoped to `Workers Scripts: Edit`, held as `CLOUDFLARE_WORKERS_TOKEN`. It is deliberately separate from `CLOUDFLARE_API_TOKEN` (`Email Sending: Edit`): one credential able to both send mail as the domain and replace the Worker that receives it would let a single leak both phish users and intercept every inbound message.

Two gaps are known and accepted rather than closed. **Rotating `EMAIL_INBOUND_SECRET` has a brief window**: the cluster and the Worker are updated by consecutive steps, not atomically, so mail arriving between them is rejected `401` and — because the Worker calls `setReject` — bounces permanently. Supporting two valid secrets would close it, but that is permanent complexity guarding an event that happens approximately never and self-heals in about a minute; `operations.md` documents a supervised rotation procedure instead. **Worker-side changes to the payload are caught by review, not tests** — `contract/inbound-payload.json` is generated from the Worker's own `buildPayload` and asserted from the Python side, so plugin-side drift fails loudly, but nothing forces the Worker to keep matching it beyond the Worker being small enough to read.

The Worker must not read `Authentication-Results`. Mail delivered to a Worker carries no such header and an `ARC-Authentication-Results` of only `arc=none` (cloudflare/workerd#6740), so a check there would silently pass everything. Cloudflare's MX already rejects mail failing the sender's DMARC policy before the Worker runs, and sender trust beyond that comes from the Connection's allowlist.

## Revisit when

Cloudflare adds an HTTPS destination to Email Routing, which would remove the need for a Worker entirely. Or the Worker starts accumulating branching logic — at that point its payload construction deserves its own tests rather than the review-plus-generated-contract arrangement above, and a JavaScript test runner becomes worth the third framework this repo currently avoids.
