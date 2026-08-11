// Drives the OpenClaw telemetry-push plugin so tests can assert on the
// telemetry it really posts, rather than on its source text.
//
// Usage: node openclaw_telemetry_driver.mjs <plugin-index.js> <steps.json>
// where steps.json is [{ "hook": ..., "event": {...}, "ctx": {...} }, ...].
//
// The plugin's flush timer keeps this process alive; the calling test
// terminates it once the expected payload has arrived.
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

for (const step of JSON.parse(readFileSync(stepsPath, "utf8"))) {
  const handler = handlers.get(step.hook);
  if (!handler) {
    console.error(`no handler registered for hook: ${step.hook}`);
    process.exit(2);
  }
  await handler(step.event ?? {}, step.ctx ?? {});
}
