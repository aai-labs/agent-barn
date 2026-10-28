"use client";

import { parseAsString, useQueryState } from "nuqs";

import { parseOpenTask, serializeOpenTask, type OpenTask } from "../utils";

/**
 * The Task open in the detail dialog, kept in the URL so it can be linked to. Opening pushes a
 * history entry, so Back closes it; closing replaces that entry, so Back does not reopen it.
 */
export function useOpenTask() {
  const [value, setValue] = useQueryState("task", parseAsString.withOptions({ scroll: false }));
  return [
    parseOpenTask(value),
    (task: OpenTask | null) => void setValue(serializeOpenTask(task), { history: task ? "push" : "replace" }),
  ] as const;
}
