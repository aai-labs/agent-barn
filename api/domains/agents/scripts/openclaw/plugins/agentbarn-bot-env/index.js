import fs from "node:fs";
import path from "node:path";

const SECRET_ROOT = process.env.BOT_SECRET_ROOT || "/run/agentbarn/bots";
const STATE = "/home/node/.openclaw";
const MAIN = "main";
const CODE_MODE_EXEC = "code_mode_exec";
const DEFAULT_ACCOUNT = "default";
const UNROUTED_CHANNELS = new Set(["", "last", "current"]);
const SCHEDULER_WRITES = new Set(["add", "update"]);
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

function ownAccount(agentId) {
  return agentId === MAIN ? DEFAULT_ACCOUNT : agentId;
}

function pinRoute(route, agentId, platforms) {
  if (!route || typeof route !== "object") return { route };
  const own = ownAccount(agentId);
  if (route.accountId && route.accountId !== own) return { refused: "another agent's account" };
  const channel = String(route.channel || "").trim().toLowerCase();
  if (UNROUTED_CHANNELS.has(channel)) return { route };
  if (!platforms.includes(channel)) return { refused: `no account of its own on ${channel}` };
  return { route: { ...route, accountId: own }, changed: route.accountId !== own };
}

function refusal(reason) {
  return { block: true, blockReason: `agentbarn-bot-env: an agent can only post from its own account (${reason})` };
}

function guardMessage(params, agentId, platforms) {
  const pinned = pinRoute(params, agentId, platforms);
  if (pinned.refused) return refusal(pinned.refused);
  return pinned.changed ? { params: pinned.route } : undefined;
}

function guardScheduler(params, agentId, platforms) {
  if (!SCHEDULER_WRITES.has(params.action) || !params.job || typeof params.job !== "object") return undefined;
  const job = { ...params.job };
  let changed = false;
  for (const field of ["delivery", "failureAlert"]) {
    const pinned = pinRoute(job[field], agentId, platforms);
    if (pinned.refused) return refusal(pinned.refused);
    if (pinned.changed) {
      job[field] = pinned.route;
      changed = true;
    }
  }
  if (job.delivery && typeof job.delivery === "object" && job.delivery.failureDestination) {
    const pinned = pinRoute(job.delivery.failureDestination, agentId, platforms);
    if (pinned.refused) return refusal(pinned.refused);
    if (pinned.changed) {
      job.delivery = { ...job.delivery, failureDestination: pinned.route };
      changed = true;
    }
  }
  return changed ? { params: { ...params, job } } : undefined;
}

export default {
  id: "agentbarn-bot-env",
  name: "Agent Barn Bot env",
  description: "Give each agent's commands its own values and keep its posts on its own accounts",
  register(api) {
    const parentNames = Array.isArray(api.pluginConfig?.parentNames) ? api.pluginConfig.parentNames : [];
    const platformsByAgent = api.pluginConfig?.platforms || {};
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
    api.on(
      "before_tool_call",
      (event, ctx) => {
        const agentId = ctx?.agentId;
        if (!agentId) throw new Error("agentbarn-bot-env: no agent for this message");
        const platforms = Array.isArray(platformsByAgent[agentId]) ? platformsByAgent[agentId] : [];
        const params = event.params || {};
        return event.toolName === "message"
          ? guardMessage(params, agentId, platforms)
          : guardScheduler(params, agentId, platforms);
      },
      { priority: -1000, matcher: ["message", "automations", "cron"] },
    );
  },
};
