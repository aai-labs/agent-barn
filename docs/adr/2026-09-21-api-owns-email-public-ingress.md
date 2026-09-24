# Product API owns public inbound-email ingress

Status: Accepted
Date: 2026-09-21
Origin: Maintainer decision to retire the dedicated Communications Gateway

The Cloudflare Email Worker continues to post the stable `/communications/v1/webhooks/email/inbound` contract, but the product API composes that endpoint. It invokes the existing email-admission and durable-delivery workflow in-process rather than proxying the request to the Communications process. This removes an email-specific ingress split and makes the public webhook boundary consistent with the native-platform migration while preserving the tested delivery and anti-enumeration behavior.

## Consequences

- The API Deployment must receive `EMAIL_INBOUND_SECRET`, which it already receives from the shared chart Secret.
- Ingress routes all of `/communications/v1/webhooks` to the API; no email-specific Communications Service route remains.
- The Communications process still owns the runtime-neutral delivery protocol, outbound processing, and gateway-owned fallback paths until those responsibilities migrate independently.
