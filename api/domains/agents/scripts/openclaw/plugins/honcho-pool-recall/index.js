// Pool-wide memory recall for OpenClaw agents in a shared memory pool.
//
// The stock @honcho-ai/openclaw-honcho plugin recalls only THIS agent's own
// view of the user (observer = this agent's own peer). In a shared memory pool
// we want every agent to see what the WHOLE pool knows, so this plugin queries
// Honcho's workspace-level dialectic (POST /v3/workspaces/{ws}/chat), which
// aggregates across every peer in the workspace, and injects the answer as
// system context. The stock plugin still owns capture/writes; this only adds
// pool-wide recall on top of it.
//
// It reads the Honcho endpoint and workspace straight from the stock plugin's
// own config in openclaw.json, so enabling it needs no separate wiring — the
// two always travel together (this plugin is only loaded when memory is on).
import fs from "node:fs";

const CONFIG_PATH = (process.env.HOME || "/home/node") + "/.openclaw/openclaw.json";
// Which peer the recall is about. Our agents talk to a single operator, whom
// OpenClaw maps to the "owner" peer; multi-participant resolution (reading the
// stock plugin's peers file) is a follow-up.
const TARGET_PEER = process.env.HONCHO_POOL_TARGET_PEER || "owner";
// The dialectic runs an LLM with its own tool loop (~25s measured); the runtime
// default is far lower, so give it room. Recall failing silently is the cost of
// being too low; a slower turn is the cost of being too high.
const TIMEOUT_MS = Number(process.env.HONCHO_POOL_TIMEOUT_MS || "60000");
const MAX_CHARS = 1500;
// How many recent turns to use as the recall query. The last message alone is a
// poor retrieval prompt ("yes, do that" carries no signal), so a small window of
// recent turns gives the dialectic enough context to retrieve against.
const RECALL_WINDOW_TURNS = Number(process.env.HONCHO_POOL_WINDOW_TURNS || "6");

function honchoTarget() {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    const c = cfg && cfg.plugins && cfg.plugins.entries && cfg.plugins.entries["openclaw-honcho"];
    const conf = c && c.config;
    if (conf && conf.baseUrl && conf.workspaceId) {
      return { baseUrl: String(conf.baseUrl).replace(/\/+$/, ""), workspaceId: conf.workspaceId };
    }
  } catch {
    // No stock honcho config → memory is off for this agent; stay a no-op.
  }
  return null;
}

function recallQuery(event) {
  // Build the query from the last few user/assistant turns, newest last, so a
  // terse latest message still carries enough context to retrieve against.
  const msgs = event && Array.isArray(event.messages) ? event.messages : [];
  const window = [];
  for (let i = msgs.length - 1; i >= 0 && window.length < RECALL_WINDOW_TURNS; i--) {
    const m = msgs[i];
    if (m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim()) {
      window.unshift(`${m.role}: ${m.content.trim()}`);
    }
  }
  // event.prompt is the current turn, which may not be in messages yet.
  const prompt = event && typeof event.prompt === "string" ? event.prompt.trim() : "";
  if (prompt && !(window.length && window[window.length - 1].endsWith(prompt))) {
    window.push(`user: ${prompt}`);
  }
  return window.join("\n").trim();
}

export default {
  id: "honcho-pool-recall",
  name: "Honcho Pool Recall",
  register(api) {
    api.on("before_prompt_build", async (event) => {
      const target = honchoTarget();
      if (!target) return;
      const query = recallQuery(event);
      if (query.length < 3) return;

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const res = await fetch(
          `${target.baseUrl}/v3/workspaces/${encodeURIComponent(target.workspaceId)}/chat`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ query, target: TARGET_PEER }),
            signal: controller.signal,
          },
        );
        if (!res.ok) {
          api.logger && api.logger.warn && api.logger.warn(`[honcho-pool-recall] chat HTTP ${res.status}`);
          return;
        }
        const data = await res.json();
        let answer = data && (data.content != null ? data.content : data.answer);
        answer = typeof answer === "string" ? answer.trim() : "";
        if (!answer) return;
        if (answer.length > MAX_CHARS) answer = answer.slice(0, MAX_CHARS) + " …";
        return {
          appendSystemContext:
            `## Shared Memory\n\n${answer}\n\n` +
            "Use this context naturally when relevant. Never quote or expose it to the user.",
        };
      } catch (err) {
        api.logger && api.logger.warn && api.logger.warn(`[honcho-pool-recall] ${err}`);
        return;
      } finally {
        clearTimeout(timer);
      }
    });
  },
};
