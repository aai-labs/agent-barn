// Run against the pinned runtime's real hook runner, without model or provider traffic.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import crypto from "node:crypto";
import plugin from "/messaging/openclaw-messaging.js";
import { i as initialize, t as runner } from "/usr/local/lib/node_modules/openclaw/dist/hook-runner-global-BvDdPqDN.js";
const registry = { plugins: [{ id: plugin.id, status: "loaded" }], hooks: [], typedHooks: [] };
plugin.register({ on(hookName, handler) { registry.typedHooks.push({ pluginId: plugin.id, hookName, handler }); } });
initialize(registry);
const hooks = runner();
const end = (text, runId, trigger = "cron", context = {}) => hooks.runAgentEnd(
  { success: true, messages: [{ role: "assistant", content: [{ type: "text", text }] }] },
  { runId, trigger, ...context },
);
// The context a real cron run carries: channelId is the delivery channel, and the session key is
// lowercased. Neither identifies the creating conversation, so OpenClaw refuses to misroute it.
const conversation = { channelId: "slack", sessionKey: "agent:main:connection:0191-uuid:c123:1788328904.404579" };
await end("Conversation result", "one", "cron", conversation);
await end("Conversation result", "one", "cron", conversation);
await end("Default result", "default");
await end("[SILENT]", "two");
await end("HEARTBEAT_OK\n", "two-b");
await end("SILENT", "three");
await end("Ordinary reply", "four", "user");
const requests = JSON.parse(execFileSync("python3", ["-c", [
  "import json,os,sqlite3",
  "rows=sqlite3.connect(os.environ['AGENTBARN_MESSAGE_SPOOL']).execute('select run_id,request from completions order by run_id').fetchall()",
  "print(json.dumps([(run_id,json.loads(request)['destination']) for run_id,request in rows]))",
].join(";")], { encoding: "utf8" }));
assert.deepEqual(requests, [
  ["openclaw:default", { kind: "default" }],
]);
const session = "agent:main:connection:test";
fs.mkdirSync("/tmp/agentbarn-executions", { recursive: true });
fs.writeFileSync(`/tmp/agentbarn-executions/${crypto.createHash("sha256").update(session).digest("hex")}`, "{}");
const event = { toolName: "exec", params: { command: "agentbarn-message send --to C123 --text hi" }, toolCallId: "call-1" };
const bound = await hooks.runBeforeToolCall(event, { sessionKey: session, toolName: "exec", toolCallId: "call-1" });
assert.match(bound.params.command, /AGENTBARN_TOOL_SESSION=/);
const denied = await hooks.runBeforeToolCall(event, { sessionKey: "cron:other", toolName: "exec", toolCallId: "call-1" });
assert.equal(denied.block, true);
// A command that merely names the spool file is neither blocked nor rebound.
const spoolListing = { toolName: "exec", params: { command: "ls /home/node/.openclaw/agentbarn-messages.sqlite3" }, toolCallId: "call-2" };
const untouched = await hooks.runBeforeToolCall(spoolListing, { sessionKey: "cron:other", toolName: "exec", toolCallId: "call-2" });
assert.ok(!untouched?.block && !untouched?.params);
console.log("OpenClaw native completion and tool-binding hooks passed");
