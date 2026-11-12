import { o as loadPlugins } from "/usr/local/lib/node_modules/openclaw/dist/loader-DhyKX__3.js";
import { i as initialize, t as runner } from "/usr/local/lib/node_modules/openclaw/dist/hook-runner-global-ac8FBwry.js";

const [botA, parentNames] = [process.env.BOT_A, JSON.parse(process.env.PARENT_NAMES)];
const config = {
  plugins: {
    allow: ["agentbarn-bot-env", "exec-rewriter"],
    load: { paths: ["/tmp/plugins/agentbarn-bot-env", "/tmp/plugins/exec-rewriter"] },
    entries: {
      "agentbarn-bot-env": { enabled: true, config: { parentNames } },
      "exec-rewriter": { enabled: true },
    },
  },
};
const registry = loadPlugins({ config, workspaceDir: "/tmp", onlyPluginIds: ["agentbarn-bot-env", "exec-rewriter"], cache: false });
initialize(registry);
const hooks = runner();

async function call(agentId, event) {
  try {
    const result = await hooks.runBeforeToolCall(event, { agentId, sessionKey: `agent:${agentId}:contract`, toolName: event.toolName });
    return { result: result ?? null };
  } catch (error) {
    return { error: String(error.message || error) };
  }
}

const exec = { toolName: "exec", params: { command: "echo hi", env: { EXTRA: "kept" } } };
console.log(
  JSON.stringify({
    diagnostics: registry.diagnostics ?? [],
    bot: await call(botA, exec),
    parent: await call("main", exec),
    unknown: await call("0000000c-0000-4000-8000-00000000000c", exec),
    read: await call(botA, { toolName: "read", params: { path: "x" } }),
  }),
);
