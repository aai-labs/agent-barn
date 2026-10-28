"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { formatDate } from "@/shared/date";

import { useTasks, type TaskScope } from "../hooks/use-agent-tasks";
import type { AgentTask, AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_LABEL } from "../utils";
import { TaskDetailDialog } from "./task-detail-dialog";

function TaskBoardColumn({
  scope,
  status,
  agentName,
  onOpen,
}: {
  scope: TaskScope;
  status: AgentTaskStatus;
  agentName?: (agentId: string) => string | undefined;
  onOpen: (task: AgentTask) => void;
}) {
  const { tasks, total, isLoading, error, refetch, hasMore, loadMore, isLoadingMore } = useTasks(scope, status);
  const label = TASK_STATUS_LABEL[status];

  return (
    <section
      aria-label={`${label} tasks`}
      className="flex min-w-[15rem] flex-1 flex-col rounded-xl p-2"
      style={{ background: "var(--bg-sunken)" }}
    >
      <h3 className="m-0 flex items-center gap-2 px-2 py-1.5 text-[0.84rem] font-semibold">
        {label}
        {!isLoading && !error && (
          <span className="text-[0.78rem] font-normal" style={{ color: "var(--ink-4)" }}>
            {total}
          </span>
        )}
      </h3>
      {isLoading ? (
        <p className="m-0 px-2 py-2 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
          Loading tasks…
        </p>
      ) : error ? (
        <div className="p-1">
          <AppErrorState error={error} title="Could not load tasks" onRetry={() => void refetch()} />
        </div>
      ) : tasks.length === 0 ? (
        <p className="m-0 px-2 py-2 text-[0.82rem]" style={{ color: "var(--ink-4)" }}>
          No tasks.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {tasks.map((task) => (
            <li key={task.id}>
              <button
                type="button"
                data-testid="task-card"
                className="af-card block w-full px-3 py-2.5 text-left hover:bg-[var(--bg-soft)]"
                onClick={() => onOpen(task)}
              >
                <span className="block text-[0.88rem] font-medium">{task.title}</span>
                <span className="mt-1 block text-[0.76rem]" style={{ color: "var(--ink-4)" }}>
                  {[agentName?.(task.agentId), `Updated ${formatDate(task.updatedAt)}`].filter(Boolean).join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {hasMore && (
        <button
          type="button"
          className="af-btn af-btn-sm mt-2 self-start"
          disabled={isLoadingMore}
          onClick={() => void loadMore()}
        >
          {isLoadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}

/** Tasks in a column per status, each card opening its notes and files. */
export function TaskBoard({
  scope,
  agentName,
}: {
  scope: TaskScope;
  /** Names each Task's Agent, on boards that span Agents. */
  agentName?: (agentId: string) => string | undefined;
}) {
  const [openTask, setOpenTask] = useState<AgentTask | null>(null);
  return (
    <div className="overflow-x-auto">
      <div className="flex gap-3 pb-1">
        {TASK_STATUSES.map((status) => (
          <TaskBoardColumn key={status} scope={scope} status={status} agentName={agentName} onOpen={setOpenTask} />
        ))}
      </div>
      <TaskDetailDialog task={openTask} onClose={() => setOpenTask(null)} />
    </div>
  );
}
