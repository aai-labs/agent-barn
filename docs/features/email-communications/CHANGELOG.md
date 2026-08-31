# Email communications — change log

Status: Active
Epic: AF-276 Email communication platform
Related context: [Communications](../communications/CHANGELOG.md), [Agents](../agents.md), [Operations](../../guidelines/operations.md), [gateway ownership ADR](../../adr/2026-08-22-agent-barn-owned-communications-gateway.md)

## Current state

- Delivered: `Email` carries an optional per-message sender address, plain-text part, `Reply-To`, and custom headers, and `EmailClient` maps them onto the Cloudflare Email Sending REST payload. Configuration gates agent email behind `is_agent_email_enabled`.
- In transition: nothing is wired to Agents yet. No Email Platform Plugin, no address allocation, no inbound route, and no Cloudflare agent domain — an Agent cannot send or receive mail. The new `Email` fields are used only by tests.
- Next: address allocation (`agent_email_address` table, claim on Connection create, release on retire and on Agent deletion).
- Blockers: none in code. Rollout needs `agents.agentbarn.dev` onboarded for both Email Routing and Email Sending in Cloudflare, which is dashboard work with up to 24 hours of verification latency.

## Scope

Slice 1 is **inbound and reply only**. An Agent answers mail sent to its own address; it cannot start a conversation. Agent-initiated ("cold") outbound needs a gateway path for an outbound delivery with no source inbound delivery, a recipient policy, and a way for a runtime to invoke it — none of which exist — and is deliberately deferred.

The reply-only scope carries the slice's main security property: `RuntimeReplyCreate` has no recipient field, and `enqueue_runtime_reply` copies the location from the source inbound delivery, so an Agent **structurally cannot** address a third party. Recipient policy is a consequence of the data model rather than configuration that can be misconfigured.

## Constraints that shape the design

Confirmed against Cloudflare's documentation while planning; recorded here because each one closes off an approach that looks reasonable otherwise.

- **The send REST API returns no message id** — only `delivered`/`queued`/`permanent_bounces`. We can never learn the `Message-ID` Cloudflare assigned to our own outbound mail, so threads cannot be anchored on it. Threading anchors on the References root instead, which survives every hop because a replying client copies the parent's `References` and appends its `Message-ID`.
- **Catch-all is zone-apex only**, and making a subdomain its own zone is Enterprise-only. Subaddressing (RFC 5233) is supported and preserves the `+tag` in `message.to`, so one routing rule on `agent@agents.agentbarn.dev` serves every Agent with no per-Agent Cloudflare API call and no 200-rule ceiling.
- **Email Workers cannot read SPF/DKIM/DMARC verdicts.** Worker-delivered mail arrives with no `Authentication-Results` and an `ARC-Authentication-Results` of only `arc=none` (cloudflare/workerd#6740). Cloudflare's MX still rejects mail failing the sender's DMARC policy, but the Worker cannot verify anything itself, so sender trust must come from the Agent Barn allowlist.
- Header allowlist covers `In-Reply-To`, `References` and `Auto-Submitted`, capped at 2048 bytes per header value — long `References` chains must be truncated to root plus most recent.
- The Cloudflare daily send quota is **per account and shared with invites, password resets, staging and production** (`../../guidelines/operations.md`). Agent mail draws from the same pool.

## Changes

### 2026-08-31 — AF-276 — Email infrastructure supports per-message sender, text, Reply-To and headers — PR pending

- Delivered: `Email` gained optional `text_part`, `from_email`, `reply_to` and `headers`. `EmailClient._build_payload` sends as `from_email` when supplied and falls back to the configured `SENDER_EMAIL` otherwise, and emits `text`, `reply_to` and `headers` only when set. `html` is now omitted rather than sent empty, so a plain-text-only message is a genuine single-part message — Cloudflare requires at least one of `html`/`text`.
- Changed: `Config` gained `agent_email_domain`, `agent_email_mailbox` (default `agent`) and `email_inbound_secret`, plus `is_agent_email_enabled`, which requires transactional delivery *and* all three agent values. Transactional delivery is unaffected: `is_email_delivery_enabled` and the client's disabled-delivery guard are unchanged, so an environment with no agent domain keeps sending invites and resets exactly as before.
- Notes: A regression test asserts the payload for a message with no agent fields set is byte-identical to the previous shape, because every invite, password reset and lifecycle notification flows through the same builder. No test reaches Cloudflare — `conftest.py` forces fake credentials over any `.env` values and an autouse fixture raises on any request to `api.cloudflare.com`.
- Follow-up: `agent_email_mailbox` and `email_inbound_secret` are read by nothing yet; they are consumed by the address allocator and the inbound route in the next two slices.
