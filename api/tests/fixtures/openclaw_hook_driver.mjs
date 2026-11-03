// Drives an OpenClaw plugin's hooks and prints what each one returned, so tests
// can assert on decisions a plugin makes rather than on its source text.
//
// Usage: node openclaw_hook_driver.mjs <plugin-index.js> <steps.json>
// where steps.json is [{ "hook": ..., "event": {...}, "ctx": {...} }, ...].
// An optional third file gives { "pluginConfig": {...}, "slack": {...} }. "slack"
// maps a Slack API method to its reply, or to { "throw": message }. Requests are
// printed with the results, as { "results": [...], "requests": [...] }.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , pluginPath, stepsPath, setupPath] = process.argv;
const setup = setupPath ? JSON.parse(readFileSync(setupPath, "utf8")) : {};
const requests = [];
if (setup.slack) {
  globalThis.fetch = async (url, options) => {
    const parsed = new URL(url);
    const method = parsed.pathname.split("/").pop();
    requests.push({
      method,
      params: Object.fromEntries(parsed.searchParams),
      authorization: options?.headers?.Authorization,
    });
    const reply = setup.slack[method] ?? { ok: false, error: "unknown_method" };
    if (reply.throw) throw new Error(reply.throw);
    return { json: async () => reply };
  };
}

const { default: plugin } = await import(pathToFileURL(pluginPath).href);

const handlers = new Map();
plugin.register({
  pluginConfig: setup.pluginConfig,
  on(name, fn) {
    handlers.set(name, fn);
  },
});

const results = [];
for (const step of JSON.parse(readFileSync(stepsPath, "utf8"))) {
  const handler = handlers.get(step.hook);
  if (!handler) {
    console.error(`no handler registered for hook: ${step.hook}`);
    process.exit(2);
  }
  const result = await handler(step.event ?? {}, step.ctx ?? {});
  results.push(result ?? null);
}
console.log(JSON.stringify(setupPath ? { results, requests } : results));
