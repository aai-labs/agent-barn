import PostalMime from "postal-mime";

import { buildPayload } from "./payload.js";

const MAX_INBOUND_BYTES = 25 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 15_000;

// Agent Barn owns every admission decision — sender policy, automated-mail guards,
// threading. This Worker only parses and forwards, so the rules stay in the Python
// plugin where they are tested. Deliberately absent: any SPF/DKIM/DMARC check.
// Worker-delivered mail carries no Authentication-Results header and an
// ARC-Authentication-Results of only "arc=none" (cloudflare/workerd#6740), so reading
// them would pass everything. Cloudflare's MX already rejects DMARC failures upstream.

export default {
  async email(message, env) {
    if (message.rawSize > MAX_INBOUND_BYTES) {
      message.setReject("Message too large");
      return;
    }

    const parsed = await PostalMime.parse(message.raw);
    const payload = buildPayload(parsed, message.to, message.headers);

    let response;
    try {
      response = await fetch(env.INBOUND_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.EMAIL_INBOUND_SECRET}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch (cause) {
      // Reject rather than swallow: the sender gets a bounce they can act on,
      // instead of the message disappearing with no trace on either side.
      message.setReject(`Could not reach Agent Barn: ${cause}`);
      return;
    }

    if (!response.ok) {
      message.setReject(`Agent Barn rejected the message (HTTP ${response.status})`);
    }
  },
};
