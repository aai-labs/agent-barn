"use client";

import { AppErrorState } from "@/components/app-error-state";

import { useTasks, type TaskScope } from "../hooks/use-agent-tasks";
import type { AgentTaskStatus, AgentTaskSummary } from "../schemas";
import { TaskStatusBadge } from "./task-status-badge";
import { TASK_FOCUS_RING, TaskSummaryMeta } from "./task-summary";

/** A paged list of Tasks, each opening its notes and files. */
export function TaskList({
  scope,
  status,
  emptyMessage,
  agentName,
  onOpen,
}: {
  scope: TaskScope;
  status: AgentTaskStatus | null;
  emptyMessage: string;
  /** Names each Task's Agent, on lists that span Agents. */
  agentName?: (agentId: string) => string | undefined;
  onOpen: (task: AgentTaskSummary) => void;
}) {
  const { tasks, isLoading, error, refetch, hasMore, loadMore, isLoadingMore } = useTasks(scope, status);

  return (
    <section className="af-card overflow-hidden" aria-label="Tasks">
      {isLoading ? (
        <div role="status" className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Loading tasks…
        </div>
      ) : error ? (
        <div className="p-5">
          <AppErrorState error={error} title="Could not load tasks" onRetry={() => void refetch()} />
        </div>
      ) : tasks.length === 0 ? (
        <div role="status" className="px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
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
                className={`flex w-full items-start justify-between gap-3 px-5 py-3 text-left hover:bg-[var(--bg-soft)] ${TASK_FOCUS_RING} focus-visible:-outline-offset-2`}
                onClick={() => onOpen(task)}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{task.title}</span>
                  <TaskSummaryMeta task={task} agentName={agentName?.(task.agentId)} />
                </span>
                <span className="shrink-0 pt-0.5">
                  <TaskStatusBadge status={task.status} />
                </span>
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
    </section>
  );
}
