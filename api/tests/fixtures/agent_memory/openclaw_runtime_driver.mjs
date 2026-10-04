// Use the pinned core's real loader, manifest validation, service, and hook runner.
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { o as loadPlugins } from "/usr/local/lib/node_modules/openclaw/dist/loader-DhyKX__3.js";
import { i as initialize, t as runner } from "/usr/local/lib/node_modules/openclaw/dist/hook-runner-global-ac8FBwry.js";

const state = process.env.HOME + "/.openclaw";
const savedConfig = fs.readFileSync(state + "/openclaw.json", "utf8");
const config = JSON.parse(savedConfig);
const registry = loadPlugins({
  config,
  workspaceDir: state + "/workspace",
  onlyPluginIds: ["memory-core", "hindsight-openclaw"],
  resolveRawConfigEnvVars: true,
  cache: false,
});
initialize(registry);
const hooks = runner();
const services = registry.services.filter((entry) => entry.pluginId === "hindsight-openclaw");
let recalled = "";
try {
  for (const entry of services) await entry.service.start();
  const ctx = {
    agentId: "main",
    sessionKey: "agent:main:connection:memory-contract:new-session",
    messageProvider: "webchat",
    channelId: "memory-contract",
    senderId: "contract-user",
  };
  const prompt = "What is our release convention? Please remember this conversation.";
  const built = await hooks.runBeforePromptBuild({ prompt, rawMessage: prompt, messages: [] }, ctx);
  recalled = JSON.stringify(built ?? {});
  await hooks.runAgentEnd({
    success: true,
    messages: [
      { role: "user", content: [{ type: "text", text: prompt }] },
      { role: "assistant", content: [{ type: "text", text: "Memory contract response." }] },
    ],
  }, ctx);
} finally {
  for (const entry of services) await entry.service.stop();
}
const organizationTool = process.env.MEMORY_API_KEY ? spawnSync("agentbarn-memory", ["remember-organization"], {input: "Organization release convention.", encoding: "utf8", timeout: 15000}) : null;
console.log("MEMORY_RUNTIME_CONTRACT=" + JSON.stringify({
  providers: registry.plugins.filter((entry) => entry.status === "loaded").map((entry) => entry.id),
  plugin_errors: registry.plugins.filter((entry) => entry.status === "error").map((entry) => entry.error),
  recalled,
  organization_tool_exit: organizationTool?.status ?? null,
  organization_tool_error: organizationTool?.stderr ?? "",
  native_prompt: fs.readFileSync(state + "/workspace/USER.md", "utf8") + fs.readFileSync(state + "/workspace/MEMORY.md", "utf8"),
  saved_settings_exist: Object.hasOwn(config.plugins.entries["hindsight-openclaw"], "config"),
  saved_credential: savedConfig.includes(process.env.MEMORY_API_KEY ?? "absent-credential"),
}));
