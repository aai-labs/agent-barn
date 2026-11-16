"use client";

import Link from "next/link";
import { Download, Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatBytes } from "@/features/resource-usage/format";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import { useAgentTask, useDownloadTaskFile } from "../hooks/use-agent-task";
import type { AgentTaskDetail } from "../schemas";
import type { OpenTask } from "../utils";
import { TaskStatusBadge } from "./task-status-badge";

const SECTION_HEADING = "mb-2 mt-0 text-[0.84rem] font-semibold";

function TaskFiles({ task }: { task: AgentTaskDetail }) {
  const download = useDownloadTaskFile(task.agentId, task.id);
  if (task.files.length === 0) {
    return (
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        No files.
      </p>
    );
  }
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {task.files.map((file) => (
        <li
          key={file.id}
          className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2"
          style={{ borderColor: "var(--line)" }}
        >
          <div className="min-w-0">
            <div className="truncate text-[0.86rem] font-medium" title={file.filename}>
              {file.filename}
            </div>
            <div className="text-[0.76rem]" style={{ color: "var(--ink-3)" }}>
              {formatBytes(file.sizeBytes)} · {formatDate(file.createdAt)}
            </div>
          </div>
          <button
            type="button"
            className="af-btn af-btn-sm shrink-0"
            aria-label={`Download ${file.filename}`}
            onClick={() => void download(file).catch((error) => toastError(error, "Could not download the file"))}
          >
            <Download size={13} aria-hidden /> Download
          </button>
        </li>
      ))}
    </ul>
  );
}

function TaskNotes({ task }: { task: AgentTaskDetail }) {
  if (task.notes.length === 0) {
    return (
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        No notes.
      </p>
    );
  }
  return (
    <ol className="m-0 list-none space-y-3 p-0">
      {task.notes.map((note) => (
        <li key={note.id} className="border-l pl-3" style={{ borderColor: "var(--line-strong)" }}>
          <div className="text-[0.76rem]" style={{ color: "var(--ink-3)" }}>
            {formatDate(note.createdAt)}
          </div>
          <p className="m-0 whitespace-pre-wrap text-[0.86rem]">{note.body}</p>
        </li>
      ))}
    </ol>
  );
}

function TaskDates({ task }: { task: AgentTaskDetail }) {
  const started = formatDate(task.createdAt);
  const updated = formatDate(task.updatedAt);
  return started === updated ? <>{started}</> : <>Started {started} · Updated {updated}</>;
}

/**
 * The open Task with its notes and files. A failed Task leads with its notes, which say
 * what went wrong; otherwise the files it produced come first.
 */
export function TaskDetailDialog({
  openTask,
  onClose,
  agentName,
  agentHref,
}: {
  openTask: OpenTask | null;
  onClose: () => void;
  /** Named on pages that span Agents. */
  agentName?: string;
  agentHref?: string;
}) {
  const { task, isLoading, error, refetch } = useAgentTask(openTask?.agentId ?? "", openTask?.taskId ?? null);
  const files = task && (
    <section aria-labelledby="task-files-heading">
      <h3 id="task-files-heading" className={SECTION_HEADING}>
        Files
      </h3>
      <TaskFiles task={task} />
    </section>
  );
  const notes = task && (
    <section aria-labelledby="task-notes-heading">
      <h3 id="task-notes-heading" className={SECTION_HEADING}>
        Notes
      </h3>
      <TaskNotes task={task} />
    </section>
  );

  return (
    <Dialog open={openTask !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2 pr-6">
            {task?.title ?? "Task"}
            {task && <TaskStatusBadge status={task.status} />}
          </DialogTitle>
          <DialogDescription>
            {agentName &&
              (agentHref ? (
                <Link href={agentHref} className="font-medium underline-offset-2 hover:underline">
                  {agentName}
                </Link>
              ) : (
                <span className="font-medium">{agentName}</span>
              ))}
            {agentName && task && " · "}
            {task && <TaskDates task={task} />}
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div role="status" className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
            <Loader2 size={16} className="animate-spin" aria-hidden /> Loading task…
          </div>
        ) : error ? (
          <AppErrorState error={error} title="Could not load the task" onRetry={() => void refetch()} />
        ) : task ? (
          <div className="max-h-[60vh] space-y-6 overflow-auto">
            {task.description && (
              <p className="m-0 whitespace-pre-wrap text-[0.9rem] leading-relaxed">{task.description}</p>
            )}
            {task.status === "failed" ? (
              <>
                {notes}
                {files}
              </>
            ) : (
              <>
                {files}
                {notes}
              </>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
