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

  const req = http.request(options, (res) => {
    res.resume();
    if (res.statusCode >= 400) {
      console.error(`[telemetry-push] flush failed: HTTP ${res.statusCode}`);
    }
  });
  req.on("error", (err) => {
    console.error(`[telemetry-push] flush error: ${err.message}`);
  });
  req.write(body);
  req.end();
}

function nowISO() {
  return new Date().toISOString();
}

function convType(conversationId) {
  return conversationId && conversationId.startsWith("USER:") ? "DM" : "CHANNEL";
}

function extractText(msg) {
  if (typeof msg.content === "string") return msg.content;
  return (msg.content || [])
    .filter((c) => c.type === "text")
    .map((c) => c.text)
    .join("\n");
}

let counter = 0;
let lastConversationId = "";
let lastThreadId = null;

export default {
  id: "telemetry-push",
  name: "Telemetry Push",
  description: "Push messages and tool calls to the ingest API",
  register(api) {
    if (!AGENT_ID || !INGEST_URL || !INGEST_API_KEY) return;

    flushTimer = setInterval(flush, 2000);

    api.on("message_received", (event, ctx) => {
      const conversationId = (ctx.conversationId || "").toUpperCase();
      lastConversationId = conversationId;
      lastThreadId = event.threadId || null;
      const msgId =
        event.messageId || `oc:in:${conversationId}:${Date.now()}:${++counter}`;
      buffer.push({
        type: "message",
        data: {
          msg_id: msgId,
          session_key: ctx.sessionKey || "",
          channel_id: conversationId,
          thread_id: event.threadId || null,
          direction: "INBOUND",
          conversation_type: convType(conversationId),
          sender_id: event.senderId || null,
          sender_name: (event.metadata && event.metadata.senderName) || null,
          channel_name: null,
          content: event.content || "",
          occurred_at: nowISO(),
        },
      });
    });

    api.on("agent_end", (event, ctx) => {
      if (ctx.agentId !== "main") return;
      const msgs = event.messages || [];
      const conversationId =
        lastConversationId || (ctx.channelId || "").toUpperCase();

      // Outbound capture
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role !== "assistant") continue;
        const content = extractText(msgs[i]);
        if (!content) continue;
        const msgId = `oc:out:${conversationId}:${Date.now()}:${++counter}`;
        buffer.push({
          type: "message",
          data: {
            msg_id: msgId,
            session_key: ctx.sessionKey || "",
            channel_id: conversationId,
            thread_id: lastThreadId,
            direction: "OUTBOUND",
            conversation_type: convType(conversationId),
            sender_id: null,
            sender_name: null,
            channel_name: null,
            content: content,
            occurred_at: nowISO(),
          },
        });
        break;
      }

    });

    api.on("before_tool_call", (event, ctx) => {
      const externalId =
        event.toolCallId || `oc:tc:${Date.now()}:${++counter}`;
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
      const externalId =
        event.toolCallId || `oc:tr:${Date.now()}:${++counter}`;
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
  },
};
