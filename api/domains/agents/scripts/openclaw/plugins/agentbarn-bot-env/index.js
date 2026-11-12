import fs from "node:fs";
import path from "node:path";

const SECRET_ROOT = process.env.BOT_SECRET_ROOT || "/run/agentbarn/bots";
const STATE = "/home/node/.openclaw";
const MAIN = "main";
const CODE_MODE_EXEC = "code_mode_exec";
const SHARED = new Set(["FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "LITELLM_BASE_URL", "LITELLM_PROXY_TARGET", "LLM_PROXY_PORT"]);

function readSecret(agentId) {
  const directory = path.join(SECRET_ROOT, agentId);
  const secret = {};
  for (const name of fs.readdirSync(directory)) {
    if (name.startsWith("..")) continue;
    const file = path.join(directory, name);
    if (fs.statSync(file).isFile()) secret[name] = fs.readFileSync(file, "utf8");
  }
  if (secret.AGENT_ID !== agentId) throw new Error("agentbarn-bot-env: the Bot's Secret does not match it");
  return secret;
}

function parentEnv(parentNames) {
  return Object.fromEntries(parentNames.map((name) => [name, process.env[name] ?? ""]));
}

function botEnv(agentId, parentNames) {
  const env = {};
  for (const name of parentNames) if (!SHARED.has(name)) env[name] = "";
  for (const [name, value] of Object.entries(readSecret(agentId))) if (!SHARED.has(name)) env[name] = value;
  env.AAI_CONFIG = `${STATE}/bots/${agentId}/.config/aai-cli/config.toml`;
  env.ARTIFACT_UPLOAD_ROOTS = `${STATE}/workspace-${agentId}`;
  return env;
}

export default {
  id: "agentbarn-bot-env",
  name: "Agent Barn Bot env",
  description: "Give each agent's commands its own Agent Barn and integration values",
  register(api) {
    const parentNames = Array.isArray(api.pluginConfig?.parentNames) ? api.pluginConfig.parentNames : [];
    api.on(
      "before_tool_call",
      (event, ctx) => {
        if (event.toolName !== "exec") return undefined;
        const agentId = ctx?.agentId;
        if (!agentId) throw new Error("agentbarn-bot-env: no agent for this command");
        if (event.toolKind === CODE_MODE_EXEC) {
          if (agentId === MAIN) return undefined;
          throw new Error("agentbarn-bot-env: code mode is not available to Bots");
        }
        const own = agentId === MAIN ? parentEnv(parentNames) : botEnv(agentId, parentNames);
        const params = event.params || {};
        return { params: { ...params, env: { ...(params.env || {}), ...own } } };
      },
      { priority: -1000, matcher: ["exec"] },
    );
  },
};
