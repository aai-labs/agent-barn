import http from "node:http";

const AGENT_ID = process.env.AGENT_ID || "";
const INGEST_URL = process.env.INGEST_URL || "";
const INGEST_API_KEY = process.env.INGEST_API_KEY || "";

let buffer = [];
let flushTimer = null;

function flush() {
  if (buffer.length === 0) return;

  const events = buffer.splice(0);
  const messages = [];
  const toolCalls = [];
  const toolResults = [];

  for (const e of events) {
    if (e.type === "message") messages.push(e.data);
    else if (e.type === "tool_call") toolCalls.push(e.data);
    else if (e.type === "tool_result") toolResults.push(e.data);
  }

  const body = JSON.stringify({
    messages,
    tool_calls: toolCalls,
    tool_results: toolResults,
  });

  const url = new URL(`${INGEST_URL}/agents/${AGENT_ID}/events`);
  const options = {
    hostname: url.hostname,
    port: url.port,
    path: url.pathname + url.search,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${INGEST_API_KEY}`,
      "Content-Length": Buffer.byteLength(body),
    },
  };

  const req = http.request(options);
  req.on("error", () => {});
  req.write(body);
  req.end();
}

function nowISO() {
  return new Date().toISOString();
}

let counter = 0;

export function register(api) {
  if (!AGENT_ID || !INGEST_URL || !INGEST_API_KEY) return;

  flushTimer = setInterval(flush, 2000);

  api.on("message_received", (event, ctx) => {
    const msgId = event.messageId || `oc:in:${ctx.channelId}:${Date.now()}:${++counter}`;
    buffer.push({
      type: "message",
      data: {
        msg_id: msgId,
        session_key: ctx.sessionKey || "",
        channel_id: ctx.channelId || "",
        thread_id: event.threadId || null,
        direction: "INBOUND",
        conversation_type: ctx.sessionKey && ctx.sessionKey.includes(":dm:") ? "DM" : "CHANNEL",
        sender_id: event.senderId || null,
        sender_name: null,
        channel_name: null,
        content: event.content || "",
        occurred_at: nowISO(),
      },
    });
  });

  api.on("message_sent", (event, ctx) => {
    const msgId = event.messageId || `oc:out:${ctx.channelId}:${Date.now()}:${++counter}`;
    buffer.push({
      type: "message",
      data: {
        msg_id: msgId,
        session_key: ctx.sessionKey || "",
        channel_id: ctx.channelId || "",
        thread_id: event.threadId || null,
        direction: "OUTBOUND",
        conversation_type: ctx.sessionKey && ctx.sessionKey.includes(":dm:") ? "DM" : "CHANNEL",
        sender_id: null,
        sender_name: null,
        channel_name: null,
        content: event.content || "",
        occurred_at: nowISO(),
      },
    });
  });

  api.on("before_tool_call", (event, ctx) => {
    const externalId = event.toolCallId || `oc:tc:${Date.now()}:${++counter}`;
    buffer.push({
      type: "tool_call",
      data: {
        external_id: externalId,
        session_id: ctx.sessionId || ctx.sessionKey || "",
        tool_name: event.toolName || "",
        arguments: event.params || {},
        occurred_at: nowISO(),
      },
    });
  });

  api.on("after_tool_call", (event, ctx) => {
    const externalId = event.toolCallId || `oc:tr:${Date.now()}:${++counter}`;
    buffer.push({
      type: "tool_result",
      data: {
        external_id: externalId,
        result: event.result != null ? event.result : null,
        is_error: !!event.error,
        completed_at: nowISO(),
      },
    });
  });

  api.on("session_end", () => {
    flush();
  });
}
