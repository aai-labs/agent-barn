"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { formatDate } from "@/shared/date";

import { useTasks, type TaskScope } from "../hooks/use-agent-tasks";
import type { AgentTask, AgentTaskStatus } from "../schemas";
import { TaskDetailDialog } from "./task-detail-dialog";
import { TaskStatusBadge } from "./task-status-badge";

/** A paged list of Tasks, each opening its notes and files. */
export function TaskList({
  tasks,
  isLoading,
  error,
  refetch,
  hasMore,
  loadMore,
  isLoadingMore,
  emptyMessage,
  agentName,
}: {
  tasks: AgentTask[];
  isLoading: boolean;
  error: Error | null;
  refetch: () => unknown;
  hasMore: boolean;
  loadMore: () => unknown;
  isLoadingMore: boolean;
  emptyMessage: string;
  /** Names each Task's Agent, on lists that span Agents. */
  agentName?: (agentId: string) => string | undefined;
}) {
  const [openTask, setOpenTask] = useState<AgentTask | null>(null);

  return (
    <section className="af-card overflow-hidden" aria-label="Tasks">
      {isLoading ? (
        <div className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Loading tasks…
        </div>
      ) : error ? (
        <div className="p-5">
          <AppErrorState error={error} title="Could not load tasks" onRetry={() => void refetch()} />
        </div>
      ) : tasks.length === 0 ? (
        <div className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          {emptyMessage}
        </div>
      ) : (
        <ul className="m-0 list-none p-0">
          {tasks.map((task) => (
            <li
              key={task.id}
              className="border-b last:border-b-0"
              style={{ borderColor: "var(--line)" }}
              data-testid="task-row"
            >
              <button
                type="button"
                className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-3 text-left hover:bg-[var(--bg-soft)]"
                onClick={() => setOpenTask(task)}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{task.title}</span>
                  <span className="block text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
                    {[agentName?.(task.agentId), `Updated ${formatDate(task.updatedAt)}`].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <TaskStatusBadge status={task.status} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <footer className="border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
          <button type="button" className="af-btn af-btn-sm" disabled={isLoadingMore} onClick={() => void loadMore()}>
            {isLoadingMore ? "Loading…" : "Load more"}
          </button>
        </footer>
      )}
      <TaskDetailDialog task={openTask} onClose={() => setOpenTask(null)} />
    </section>
  );
}

/** The list for a scope, loading its Tasks only while it is shown. */
export function ScopedTaskList({
  scope,
  status,
  emptyMessage,
  agentName,
}: {
  scope: TaskScope;
  status: AgentTaskStatus | null;
  emptyMessage: string;
  agentName?: (agentId: string) => string | undefined;
}) {
  const tasks = useTasks(scope, status);
  return <TaskList {...tasks} emptyMessage={emptyMessage} agentName={agentName} />;
}
