import { createParser, parseAsStringLiteral } from "nuqs";

export const workflowPageParser = createParser({
  parse: (value) => {
    if (!/^[1-9]\d*$/.test(value)) return null;
    const page = Number(value);
    return Number.isSafeInteger(page) ? page : null;
  },
  serialize: String,
})
  .withDefault(1)
  .withOptions({ history: "replace", scroll: false });

export const workflowViewParser = parseAsStringLiteral([
  "overview",
  "runs",
  "history",
] as const)
  .withDefault("overview")
  .withOptions({ history: "push", scroll: false, clearOnDefault: false });
