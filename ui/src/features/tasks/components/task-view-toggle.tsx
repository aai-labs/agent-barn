"use client";

import { KanbanSquare, List } from "lucide-react";

import type { TaskView } from "../utils";
import { TASK_FOCUS_RING } from "./task-summary";

const VIEWS: { view: TaskView; label: string; icon: typeof List }[] = [
  { view: "board", label: "Board", icon: KanbanSquare },
  { view: "list", label: "List", icon: List },
];

/** Switches a Task page between its board and its list. */
export function TaskViewToggle({ value, onChange }: { value: TaskView; onChange: (view: TaskView) => void }) {
  return (
    <div
      role="group"
      aria-label="View"
      className="inline-flex rounded-lg border p-0.5"
      style={{ borderColor: "var(--line)" }}
    >
      {VIEWS.map(({ view, label, icon: Icon }) => (
        <button
          key={view}
          type="button"
          aria-pressed={value === view}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[0.82rem] ${TASK_FOCUS_RING}`}
          style={
            value === view
              ? { background: "var(--bg-soft)", color: "var(--ink)" }
              : { color: "var(--ink-3)" }
          }
          onClick={() => onChange(view)}
        >
          <Icon size={14} aria-hidden /> {label}
        </button>
      ))}
    </div>
  );
}
