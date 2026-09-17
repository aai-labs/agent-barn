// Report native channel Connection Journal stages to the ingest API.
//
// Content-free by contract: only platform, stage, correlation, timing, and a
// bounded error code leave the pod. Message text, sender identity, and provider
// error text never do.
//
// Correlation is the inbound provider message (`<platform>:<messageId>`). Runs
// and sends only carry a session key, so each is attributed to the latest
// inbound message observed on that session. Channel health is reported by
// healthz-server.js, which already polls the gateway's health snapshot.
import http from "node:http";

const FLUSH_MS = 2000;
const MAX_BUFFER = 500;
const MAX_TRACKED = 1000;

const buffer = [];
const latestInbound = new Map(); // sessionKey -> correlationId

function nativeChannels() {
  return new Set((process.env.AGENTBARN_NATIVE_CHANNELS || "").split(",").filter(Boolean));
}

function emit(stage, platform, correlationId, errorCode) {
  if (buffer.length >= MAX_BUFFER) buffer.shift();
  buffer.push({
    stage,
    platform,
    correlation_id: correlationId || null,
    occurred_at: new Date().toISOString(),
    ...(errorCode ? { error_code: errorCode } : {}),
  });
}

function correlated(sessionKey) {
  return (sessionKey && latestInbound.get(sessionKey)) || null;
}

function flush(url, apiKey) {
  if (buffer.length === 0) return;
  const body = JSON.stringify({ events: buffer.splice(0) });
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
      const correlationId = `${ctx.channelId}:${messageId}`;
      emit("provider_observed", ctx.channelId, correlationId);
      const sessionKey = ctx.sessionKey || event.sessionKey;
      if (!sessionKey) return;
      latestInbound.delete(sessionKey);
      latestInbound.set(sessionKey, correlationId);
      if (latestInbound.size > MAX_TRACKED) latestInbound.delete(latestInbound.keys().next().value);
    });

    // Cron, heartbeat, and API runs have no inbound message to report against.
    api.on("before_agent_run", (_event, ctx) => {
      const correlationId = correlated(ctx.sessionKey);
      if (correlationId) emit("agent_claimed", correlationId.split(":", 1)[0], correlationId);
    });

    api.on("agent_end", (event, ctx) => {
      const correlationId = correlated(ctx.sessionKey);
      if (correlationId) {
        emit("model_completed", correlationId.split(":", 1)[0], correlationId, event.success ? null : "model_failed");
      }
    });

    api.on("message_sent", (event, ctx) => {
      if (!native.has(ctx.channelId)) return;
      const correlationId = correlated(ctx.sessionKey || event.sessionKey);
      if (event.success) emit("provider_delivered", ctx.channelId, correlationId);
      else emit("provider_delivery_attempted", ctx.channelId, correlationId, "send_failed");
    });

    const url = `${INGEST_URL}/agents/${AGENT_ID}/communication-events`;
    setInterval(() => flush(url, INGEST_API_KEY), FLUSH_MS);
  },
};
