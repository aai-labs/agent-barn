"use client";

import { parseAsString, useQueryState } from "nuqs";

import { parseOpenTask, serializeOpenTask, type OpenTask } from "../utils";

/** The Task open in the detail dialog. Pushed to history, so Back closes it and a link reopens it. */
export function useOpenTask() {
  const [value, setValue] = useQueryState("task", parseAsString.withOptions({ history: "push", scroll: false }));
  return [parseOpenTask(value), (task: OpenTask | null) => void setValue(serializeOpenTask(task))] as const;
}
