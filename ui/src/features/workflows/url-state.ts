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

// Runs are listed on the Workflows landing page, not per workflow; old `runs` links open Overview.
export const workflowViewParser = parseAsStringLiteral([
  "overview",
  "history",
] as const)
  .withDefault("overview")
  .withOptions({ history: "push", scroll: false, clearOnDefault: false });

/** The Agent's Workflows landing: its runs (with approvals waiting) or its saved workflows. */
export const workflowsTabParser = parseAsStringLiteral(["runs", "workflows"] as const)
  .withDefault("runs")
  .withOptions({ history: "push", scroll: false });
