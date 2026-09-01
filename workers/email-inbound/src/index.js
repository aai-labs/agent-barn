import PostalMime from "postal-mime";

const MAX_INBOUND_BYTES = 25 * 1024 * 1024;
const MAX_BODY_CHARS = 100_000;
const REQUEST_TIMEOUT_MS = 15_000;

// Agent Barn owns every admission decision — sender policy, automated-mail guards,
// threading. This Worker only parses and forwards, so the rules stay in the Python
// plugin where they are tested. Deliberately absent: any SPF/DKIM/DMARC check.
// Worker-delivered mail carries no Authentication-Results header and an
// ARC-Authentication-Results of only "arc=none" (cloudflare/workerd#6740), so reading
// them would pass everything. Cloudflare's MX already rejects DMARC failures upstream.

function header(headers, name) {
  return headers.get(name) ?? "";
}

function referenceList(raw) {
  return raw.split(/\s+/).filter((entry) => entry.startsWith("<"));
}

export default {
  async email(message, env) {
    if (message.rawSize > MAX_INBOUND_BYTES) {
      message.setReject("Message too large");
      return;
    }

    const parsed = await PostalMime.parse(message.raw);
    const body = (parsed.text || parsed.html || "").slice(0, MAX_BODY_CHARS);
    const sender = parsed.from ?? {};

    const payload = {
      to: message.to,
      from: sender.address ?? message.from,
      from_name: sender.name ?? "",
      subject: parsed.subject ?? "",
      text: body,
      message_id: parsed.messageId ?? "",
      in_reply_to: parsed.inReplyTo ?? "",
      references: referenceList(parsed.references ?? ""),
      auto_submitted: header(message.headers, "auto-submitted"),
      precedence: header(message.headers, "precedence"),
      list_id: header(message.headers, "list-id"),
      received_at: (parsed.date ? new Date(parsed.date) : new Date()).toISOString(),
    };

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
