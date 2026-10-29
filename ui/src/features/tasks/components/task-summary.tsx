import { MessageSquareText, Paperclip } from "lucide-react";

import { formatDate, formatRelativeTime } from "@/shared/date";

import type { AgentTaskSummary } from "../schemas";
import { TASK_STATUS_LABEL } from "../utils";

/** Keyboard focus that stays visible on the warm surfaces Task cards and rows sit on. */
export const TASK_FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-color)]";

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** What a Task produced and when it last changed, under its title on a card or row. */
export function TaskSummaryMeta({ task, agentName }: { task: AgentTaskSummary; agentName?: string }) {
  return (
    <>
      {/* The column or badge shows status visually; this names it for screen readers. */}
      <span className="sr-only">{TASK_STATUS_LABEL[task.status]}. </span>
      <span
        className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[0.78rem]"
        style={{ color: "var(--ink-3)" }}
      >
        {agentName && <span className="font-medium">{agentName}</span>}
        <time dateTime={task.updatedAt} title={formatDate(task.updatedAt)}>
          {formatRelativeTime(task.updatedAt)}
        </time>
      </span>
      {/* Their own line, so cards of every width wrap the same way. */}
      {(task.fileCount > 0 || task.noteCount > 0) && (
        <span
          className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[0.78rem]"
          style={{ color: "var(--ink-3)" }}
        >
          {task.fileCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <Paperclip size={12} aria-hidden /> {plural(task.fileCount, "file")}
            </span>
          )}
          {task.noteCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <MessageSquareText size={12} aria-hidden /> {plural(task.noteCount, "note")}
            </span>
          )}
        </span>
      )}
      {task.status === "failed" && task.latestNote && (
        <span className="mt-1.5 line-clamp-2 block text-[0.8rem]" style={{ color: "var(--err)" }}>
          {task.latestNote}
        </span>
      )}
    </>
  );
}
