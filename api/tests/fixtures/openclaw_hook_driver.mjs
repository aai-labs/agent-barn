// Drives an OpenClaw plugin's hooks and prints what each one returned, so tests
// can assert on decisions a plugin makes rather than on its source text.
//
// Usage: node openclaw_hook_driver.mjs <plugin-index.js> <steps.json>
// where steps.json is [{ "hook": ..., "event": {...}, "ctx": {...} }, ...].
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , pluginPath, stepsPath] = process.argv;

const { default: plugin } = await import(pathToFileURL(pluginPath).href);

const handlers = new Map();
plugin.register({
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
console.log(JSON.stringify(results));
