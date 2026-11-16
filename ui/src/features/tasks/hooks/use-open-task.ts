"use client";

import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useRef } from "react";

import { parseOpenTask, serializeOpenTask, type OpenTask } from "../utils";

/**
 * The Task open in the detail dialog, kept in the URL so it can be linked to. Opening pushes a
 * history entry, so Back closes it. Closing a Task opened here steps back over that entry, so
 * no copy of the page is left behind; one opened from a link has none, so closing replaces it.
 */
export function useOpenTask() {
  const [value, setValue] = useQueryState("task", parseAsString.withOptions({ scroll: false }));
  const pushed = useRef(false);
  // Back, or a link, can close the Task without us: then there is no entry of ours left to step over.
  useEffect(() => {
    if (value === null) pushed.current = false;
  }, [value]);
  const set = (task: OpenTask | null) => {
    if (task) {
      if (pushed.current) {
        void setValue(serializeOpenTask(task), { history: "replace" });
        return;
      }
      pushed.current = true;
      void setValue(serializeOpenTask(task), { history: "push" });
    } else if (pushed.current) {
      pushed.current = false;
      window.history.back();
    } else {
      void setValue(null, { history: "replace" });
    }
  };
  return [parseOpenTask(value), set] as const;
}
