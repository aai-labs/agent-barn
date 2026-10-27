"use client";

import { Download, Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatBytes } from "@/features/resource-usage/format";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import { useAgentTask, useDownloadTaskFile } from "../hooks/use-agent-task";
import type { AgentTask, AgentTaskDetail } from "../schemas";
import { TaskStatusBadge } from "./task-status-badge";

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
            <div className="truncate text-[0.86rem] font-medium">{file.filename}</div>
            <div className="text-[0.76rem]" style={{ color: "var(--ink-4)" }}>
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
        <li key={note.id} className="border-l-2 pl-3" style={{ borderColor: "var(--line)" }}>
          <div className="text-[0.76rem]" style={{ color: "var(--ink-4)" }}>
            {formatDate(note.createdAt)}
          </div>
          <p className="m-0 whitespace-pre-wrap text-[0.86rem]">{note.body}</p>
        </li>
      ))}
    </ol>
  );
}

/** A Task with its notes and files, opened from a Task list. */
export function TaskDetailDialog({ task, onClose }: { task: AgentTask | null; onClose: () => void }) {
  const { task: detail, isLoading, error } = useAgentTask(task?.agentId ?? "", task?.id ?? null);
  return (
    <Dialog open={task !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {task?.title}
            {task && <TaskStatusBadge status={detail?.status ?? task.status} />}
          </DialogTitle>
          <DialogDescription>
            {task ? `Started ${formatDate(task.createdAt)} · Updated ${formatDate(detail?.updatedAt ?? task.updatedAt)}` : ""}
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <Loader2 size={16} className="animate-spin" aria-label="Loading task" />
        ) : error ? (
          <AppErrorState error={error} title="Could not load the task" />
        ) : detail ? (
          <div className="max-h-[60vh] space-y-5 overflow-auto">
            {detail.description && <p className="m-0 whitespace-pre-wrap text-[0.88rem]">{detail.description}</p>}
            <section aria-label="Files">
              <h4 className="mb-2 mt-0 text-[0.88rem] font-semibold">Files</h4>
              <TaskFiles task={detail} />
            </section>
            <section aria-label="Notes">
              <h4 className="mb-2 mt-0 text-[0.88rem] font-semibold">Notes</h4>
              <TaskNotes task={detail} />
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
