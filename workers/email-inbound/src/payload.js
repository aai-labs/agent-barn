export const MAX_BODY_CHARS = 100_000;

// The shape below is a contract with the Python Email Platform Plugin's
// normalize_inbound. Both sides are pinned to contract/inbound-payload.json;
// changing a key here without changing that file fails the tests on both sides.
export function buildPayload(parsed, envelopeTo, headers) {
  const sender = parsed.from ?? {};
  return {
    to: envelopeTo,
    from: sender.address ?? "",
    from_name: sender.name ?? "",
    subject: parsed.subject ?? "",
    text: (parsed.text || parsed.html || "").slice(0, MAX_BODY_CHARS),
    message_id: parsed.messageId ?? "",
    in_reply_to: parsed.inReplyTo ?? "",
    // postal-mime types `references` as a single space-separated string, not a list.
    references: referenceList(parsed.references),
    auto_submitted: header(headers, "auto-submitted"),
    precedence: header(headers, "precedence"),
    list_id: header(headers, "list-id"),
    received_at: receivedAt(parsed.date),
  };
}

function referenceList(raw) {
  return String(raw ?? "")
    .split(/\s+/)
    .filter((entry) => entry.startsWith("<"));
}

function header(headers, name) {
  return headers?.get(name) ?? "";
}

function receivedAt(raw) {
  const parsed = raw ? new Date(raw) : new Date();
  return (Number.isNaN(parsed.getTime()) ? new Date() : parsed).toISOString();
}
