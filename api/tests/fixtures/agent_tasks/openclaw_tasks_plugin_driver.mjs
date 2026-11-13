// Drives the OpenClaw agentbarn-tasks plugin through the plugin API it registers with.
//
// Usage: node openclaw_tasks_plugin_driver.mjs <plugin-index.js> <steps.json>
// Each step is {"hook": name, "event": {...}, "ctx": {...}} or {"tool": {...params}, "ctx": {...}};
// a tool registered as a factory is built with the step's ctx, as the gateway builds it for each run.
// Prints one JSON line: {"hooks": [...], "tools": [...], "results": [...]}, one result per step.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , pluginPath, stepsPath] = process.argv;
const { default: plugin } = await import(pathToFileURL(pluginPath).href);

const hooks = new Map();
const tools = new Map();
plugin.register({
  on(name, handler) {
    hooks.set(name, handler);
  },
  registerTool(tool, options) {
    tools.set(options?.name ?? tool.name, typeof tool === "function" ? tool : () => tool);
  },
});

const results = [];
let call = 0;
for (const step of JSON.parse(readFileSync(stepsPath, "utf8"))) {
  if (step.tool) {
    const tool = tools.get("agentbarn_task")(step.ctx ?? {});
    results.push(await tool.execute(`call-${call++}`, step.tool));
  } else {
    const handler = hooks.get(step.hook);
    if (!handler) {
      console.error(`no handler registered for hook: ${step.hook}`);
      process.exit(2);
    }
    results.push((await handler(step.event ?? {}, step.ctx ?? {})) ?? null);
  }
}
console.log(JSON.stringify({
  hooks: [...hooks.keys()].sort(),
  tools: [...tools.values()].map((build) => build({})).map(({ name, parameters }) => ({ name, parameters })),
  results,
}));
