import { execFileSync } from "node:child_process";
import fs from "node:fs";
import crypto from "node:crypto";

const quote = (value) => "'" + String(value).replaceAll("'", "'\\''") + "'";

export default {
  id: "agentbarn-messaging",
  name: "Agent Barn messaging",
  register(api) {
    api.on("agent_end", (event, ctx) => {
      if (ctx.trigger !== "cron" || !event.success) return;
      const runId = ctx.runId || event.runId;
      if (!runId) throw new Error("Scheduled completion has no runtime run identity");
      const assistant = [...(event.messages || [])].reverse().find((message) => message.role === "assistant");
      const content = assistant?.content;
      const text = typeof content === "string" ? content : (content || [])
        .filter((part) => part.type === "text").map((part) => part.text).join("\n");
      // Keep in step with SILENCE_MARKERS in agentbarn_message.py.
      const silent = new Set(["[silent]", "silent", "no_reply", "no reply", "heartbeat_ok"]);
      const lines = text.trim().split("\n").map((l) => l.trim()).filter(Boolean);
      if (!lines.length) return;
      if ([text.trim(), lines[0], lines[lines.length - 1]].some((c) => silent.has(c.toLowerCase()))) return;
      // Synchronous capture finishes before the hook yields; network retry is a separate process.
      execFileSync("python3", ["-c", "import json,sys; from agentbarn_message import capture_completion; p=json.load(sys.stdin); capture_completion(p['run_id'],p['text'])"], {
        input: JSON.stringify({ run_id: `openclaw:${runId}`, text }),
        env: process.env, timeout: 30000, stdio: ["pipe", "pipe", "pipe"],
      });
    });
    api.on("before_tool_call", (event, ctx) => {
      if (event.toolName !== "exec" || !event.params?.command?.includes("agentbarn-message")) return;
      const session = ctx.sessionKey;
      const invocation = event.toolCallId || ctx.toolCallId;
      const path = `${process.env.AGENTBARN_EXECUTIONS_DIR || "/tmp/agentbarn-executions"}/${crypto.createHash("sha256").update(session || "").digest("hex")}`;
      if (!session || !invocation || !fs.existsSync(path)) {
        return { block: true, blockReason: "Explicit messaging requires an active inbound execution. Scheduled delivery uses the configured default." };
      }
      return { params: { ...event.params,
        command: `AGENTBARN_TOOL_SESSION=${quote(session)} AGENTBARN_TOOL_INVOCATION=${quote(invocation)} sh -c ${quote(event.params.command)}`,
      }};
    });
  },
};
