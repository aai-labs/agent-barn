// Report native channel Journal stages and dashboard transcripts to the ingest API.
//
// Journal events stay content-free. Transcript messages are a separate payload
// collection so the dashboard can render native conversations.
//
// Correlation is the inbound provider message (`<platform>:<messageId>`). Runs
// and sends only carry a session key, so each is attributed to the latest
// inbound message observed on that session. Channel health is reported by
// healthz-server.js, which already polls the gateway's health snapshot.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const FLUSH_MS = 2000;
const MAX_BUFFER = 500;
const MAX_TRACKED = 1000;

const outbox = new Map();
const latestInbound = new Map(); // sessionKey -> correlationId
const inboundRooms = new Map(); // sessionKey -> { channel_id, thread_id }
let outboundSequence = 0;

const SECRET_ROOT = process.env.BOT_SECRET_ROOT || "/run/agentbarn/bots";
const MAIN_AGENT = "main";
const identities = new Map();

function agentOf(ctx, event) {
  if (ctx && ctx.agentId) return ctx.agentId;
  const sessionKey = (ctx && ctx.sessionKey) || (event && event.sessionKey) || "";
  const scoped = /^agent:([^:]+):/.exec(sessionKey);
  if (scoped) return scoped[1];
  const accountId = (ctx && ctx.accountId) || (event && event.accountId);
  if (accountId && accountId !== "default") return accountId;
  return MAIN_AGENT;
}

function identityFor(agent) {
  if (agent === MAIN_AGENT) {
    return { agentId: process.env.AGENT_ID || "", key: process.env.INGEST_API_KEY || "" };
  }
  if (identities.has(agent)) return identities.get(agent);
  try {
    const agentId = fs.readFileSync(path.join(SECRET_ROOT, agent, "AGENT_ID"), "utf8");
    const key = fs.readFileSync(path.join(SECRET_ROOT, agent, "INGEST_API_KEY"), "utf8");
    if (agentId !== agent || !key) return null;
    const identity = { agentId, key };
    identities.set(agent, identity);
    return identity;
  } catch {
    return null;
  }
}

function pending(agent) {
  if (!outbox.has(agent)) outbox.set(agent, { events: [], messages: [] });
  return outbox.get(agent);
}

function nativeChannels() {
  return new Set((process.env.AGENTBARN_NATIVE_CHANNELS || "").split(",").filter(Boolean));
}

function productPlatform(channelId) {
  return channelId === "msteams" ? "teams" : channelId;
}

function emit(agent, stage, platform, correlationId, errorCode) {
  const buffer = pending(agent).events;
  if (buffer.length >= MAX_BUFFER) buffer.shift();
  buffer.push({
    stage,
    platform,
    correlation_id: correlationId || null,
    occurred_at: new Date().toISOString(),
    ...(errorCode ? { error_code: errorCode } : {}),
  });
}

function emitMessage(agent, message) {
  const messages = pending(agent).messages;
  if (messages.length >= MAX_BUFFER) messages.shift();
  messages.push({ ...message, occurred_at: new Date().toISOString() });
}

function conversationType(chatType) {
  return ["dm", "direct", "direct_message"].includes(String(chatType || "").toLowerCase()) ? "DM" : "CHANNEL";
}

function channelId(event, ctx) {
  return event.chatId || event.conversationId || ctx.chatId || ctx.conversationId || event.to || "";
}

function correlated(sessionKey) {
  return (sessionKey && latestInbound.get(sessionKey)) || null;
}

function remember(map, key, value) {
  map.delete(key);
  map.set(key, value);
  if (map.size > MAX_TRACKED) map.delete(map.keys().next().value);
}

function bareChannel(location) {
  return String(location).replace(/^(channel|user):/, "");
}

function flush(ingestUrl) {
  for (const [agent, box] of outbox) {
    if (box.events.length === 0 && box.messages.length === 0) continue;
    const body = JSON.stringify({ events: box.events.splice(0), messages: box.messages.splice(0) });
    const identity = identityFor(agent);
    if (!identity) {
      console.error("[agentbarn-observer] dropped events for an agent without an identity");
      continue;
    }
    post(`${ingestUrl}/agents/${identity.agentId}/communication-events`, identity.key, body);
  }
}

function post(url, apiKey, body) {
  const request = http.request(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "Content-Length": Buffer.byteLength(body),
    },
    timeout: 10000,
  });
  request.on("response", (response) => response.resume());
  // ponytail: best-effort journal, drops on a failed flush; add retry if gaps show up in diagnostics.
  request.on("error", (error) => console.error(`[agentbarn-observer] dropped events: ${error.message}`));
  request.on("timeout", () => request.destroy(new Error("timeout")));
  request.end(body);
}

export default {
  id: "agentbarn-observer",
  name: "Agent Barn observer",
  description: "Report native channel Connection Journal stages to the ingest API",
  register(api) {
    const { AGENT_ID, INGEST_URL, INGEST_API_KEY } = process.env;
    const native = nativeChannels();
    if (!AGENT_ID || !INGEST_URL || !INGEST_API_KEY || native.size === 0) return;

    api.on("message_received", (event, ctx) => {
      const messageId = event.messageId || ctx.messageId;
      if (!native.has(ctx.channelId) || !messageId) return;
      const platform = productPlatform(ctx.channelId);
      const correlationId = `${platform}:${messageId}`;
      const agent = agentOf(ctx, event);
      emit(agent, "provider_observed", platform, correlationId);
      const sessionKey = ctx.sessionKey || event.sessionKey;
      const content = event.content || event.text;
      const location = channelId(event, ctx);
      const threadId = event.threadId || ctx.threadId || null;
      if (sessionKey && content && location) {
        emitMessage(agent, {
          platform,
          provider_message_id: String(messageId),
          session_key: sessionKey,
          channel_id: bareChannel(location),
          thread_id: threadId,
          direction: "INBOUND",
          conversation_type: conversationType(event.chatType || ctx.chatType),
          sender_id: event.senderId || ctx.senderId || null,
          sender_name: event.senderName || event.metadata?.senderName || ctx.senderName || null,
          channel_name: event.channelName || event.metadata?.channelName || ctx.channelName || null,
          content: String(content),
        });
      }
      if (!sessionKey) return;
      remember(latestInbound, sessionKey, correlationId);
      if (location) remember(inboundRooms, sessionKey, { channel_id: bareChannel(location), thread_id: threadId });
    });

    // Cron, heartbeat, and API runs have no inbound message to report against.
    api.on("before_agent_run", (_event, ctx) => {
      const correlationId = correlated(ctx.sessionKey);
      if (correlationId) emit(agentOf(ctx), "agent_claimed", correlationId.split(":", 1)[0], correlationId);
    });

    api.on("agent_end", (event, ctx) => {
      const correlationId = correlated(ctx.sessionKey);
      if (correlationId) {
        emit(agentOf(ctx, event), "model_completed", correlationId.split(":", 1)[0], correlationId, event.success ? null : "model_failed");
      }
    });

    api.on("message_sent", (event, ctx) => {
      if (!native.has(ctx.channelId)) return;
      const correlationId = correlated(ctx.sessionKey || event.sessionKey);
      const platform = productPlatform(ctx.channelId);
      const agent = agentOf(ctx, event);
      if (event.success) emit(agent, "provider_delivered", platform, correlationId);
      else emit(agent, "provider_delivery_attempted", platform, correlationId, "send_failed");
      const sessionKey = ctx.sessionKey || event.sessionKey;
      const content = event.content || event.text;
      const location = channelId(event, ctx);
      if (sessionKey && content && location) {
        outboundSequence += 1;
        const target = bareChannel(location);
        const inbound = inboundRooms.get(sessionKey);
        const sameRoom = inbound && inbound.channel_id.toLowerCase() === target.toLowerCase();
        emitMessage(agent, {
          platform,
          provider_message_id: String(event.messageId || `outbound:${sessionKey}:${outboundSequence}`),
          session_key: sessionKey,
          channel_id: sameRoom ? inbound.channel_id : target,
          thread_id: event.threadId || ctx.threadId || (sameRoom ? inbound.thread_id : null),
          direction: "OUTBOUND",
          conversation_type: conversationType(event.chatType || ctx.chatType),
          content: String(content),
        });
      }
    });

    setInterval(() => flush(INGEST_URL), FLUSH_MS);
  },
};
