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

/** A saved workflow's views: its latest version, its version history, and its runs. */
export const workflowViewParser = parseAsStringLiteral([
  "overview",
  "history",
  "runs",
] as const)
  .withDefault("overview")
  .withOptions({ history: "push", scroll: false, clearOnDefault: false });

/** The Organization's Workflows landing: runs (with approvals waiting) or saved workflows. */
export const workflowsTabParser = parseAsStringLiteral(["runs", "workflows"] as const)
  .withDefault("runs")
  .withOptions({ history: "push", scroll: false });

/** Which saved workflows the list shows. */
export const workflowFilterParser = parseAsStringLiteral(["all", "mine", "archived"] as const)
  .withDefault("all")
  .withOptions({ history: "replace", scroll: false });
