import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [pluginPath, stepsPath] = process.argv.slice(2);
const steps = JSON.parse(fs.readFileSync(stepsPath, "utf8"));
const plugin = (await import(pathToFileURL(pluginPath).href)).default;
const registrations = [];
plugin.register({
  pluginConfig: steps.config,
  on(name, handler, options) {
    registrations.push({ name, handler, options });
  },
});
const results = [];
for (const call of steps.calls) {
  const registration = registrations.find((entry) => entry.name === "before_tool_call");
  try {
    results.push({ result: (await registration.handler(call.event, call.ctx)) ?? null });
  } catch (error) {
    results.push({ error: String(error.message || error) });
  }
}
console.log(
  JSON.stringify({
    registrations: registrations.map(({ name, options }) => ({ name, options })),
    results,
  }),
);
