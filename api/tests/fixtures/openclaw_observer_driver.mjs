// Run the observer against the pinned runtime's real hook runner, without model or provider traffic.
import assert from "node:assert/strict";
import http from "node:http";
import { i as initialize, t as runner } from "/usr/local/lib/node_modules/openclaw/dist/hook-runner-global-ac8FBwry.js";

const posted = [];
const collector = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    posted.push(...JSON.parse(body).events);
    res.writeHead(204).end();
  });
});
await new Promise((resolve) => collector.listen(0, "127.0.0.1", resolve));
Object.assign(process.env, {
  AGENT_ID: "00000000-0000-0000-0000-000000000000",
  INGEST_URL: `http://127.0.0.1:${collector.address().port}`,
  INGEST_API_KEY: "ci",
  AGENTBARN_NATIVE_CHANNELS: "slack,discord",
});

const { default: plugin } = await import("/observer/index.js");
const registry = { plugins: [{ id: plugin.id, status: "loaded" }], hooks: [], typedHooks: [] };
plugin.register({ on(hookName, handler) { registry.typedHooks.push({ pluginId: plugin.id, hookName, handler }); } });
initialize(registry);
const hooks = runner();

const session = { sessionKey: "agent:main:discord:channel:1" };
await hooks.runMessageReceived(
  { from: "discord:user", content: "must not leave the runtime", messageId: "m1" },
  { channelId: "discord", ...session },
);
await hooks.runBeforeAgentRun({ prompt: "must not leave the runtime", messages: [] }, session);
await hooks.runAgentEnd({ success: true, messages: [] }, session);
await hooks.runMessageSent({ to: "channel:1", content: "reply", success: true }, { channelId: "discord", ...session });

for (let waited = 0; posted.length < 4 && waited < 10000; waited += 100) {
  await new Promise((resolve) => setTimeout(resolve, 100));
}
assert.deepEqual(
  posted.map((event) => [event.stage, event.platform, event.correlation_id]),
  [
    ["provider_observed", "discord", "discord:m1"],
    ["agent_claimed", "discord", "discord:m1"],
    ["model_completed", "discord", "discord:m1"],
    ["provider_delivered", "discord", "discord:m1"],
  ],
);
assert.ok(!JSON.stringify(posted).includes("must not leave"));
console.log("OpenClaw native observer hooks passed");
process.exit(0);
