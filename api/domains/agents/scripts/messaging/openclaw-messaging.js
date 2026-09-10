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
      const channelId = typeof ctx.channelId === "string" ? ctx.channelId.trim() : "";
      const origin = channelId.startsWith("connection:")
        ? { platform: "api_server", chat_id: channelId }
        : null;
      // Synchronous capture finishes before the hook yields; network retry is a separate process.
      // The shared client owns silence filtering and destination parsing for both runtimes.
      execFileSync("python3", ["-c", "import json,sys; from agentbarn_message import capture_completion; p=json.load(sys.stdin); capture_completion(p['run_id'],p['text'],p.get('origin'))"], {
        input: JSON.stringify({ run_id: `openclaw:${runId}`, text, origin }),
        env: process.env, timeout: 30000, stdio: ["pipe", "pipe", "pipe"],
      });
    });
    api.on("before_tool_call", (event, ctx) => {
      if (event.toolName !== "exec" || !event.params?.command?.includes("agentbarn-message")) return;
      const session = ctx.sessionKey;
      const invocation = event.toolCallId || ctx.toolCallId;
      const path = `${process.env.AGENTBARN_EXECUTIONS_DIR || "/tmp/agentbarn-executions"}/${crypto.createHash("sha256").update(session || "").digest("hex")}`;
      if (!session || !invocation || !fs.existsSync(path)) {
        return { block: true, blockReason: "Explicit messaging requires an active inbound execution. Scheduled results are delivered automatically." };
      }
      return { params: { ...event.params,
        command: `AGENTBARN_TOOL_SESSION=${quote(session)} AGENTBARN_TOOL_INVOCATION=${quote(invocation)} sh -c ${quote(event.params.command)}`,
      }};
    });
  },
};
