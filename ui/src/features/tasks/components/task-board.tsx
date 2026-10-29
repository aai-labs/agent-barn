"use client";

import { AppErrorState } from "@/components/app-error-state";

import { useTasks, type TaskScope } from "../hooks/use-agent-tasks";
import type { AgentTaskStatus, AgentTaskSummary } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_LABEL } from "../utils";
import { TASK_FOCUS_RING, TaskSummaryMeta } from "./task-summary";

type ColumnHeading = "h2" | "h3";

function TaskBoardColumn({
  scope,
  status,
  heading: Heading,
  agentName,
  onOpen,
}: {
  scope: TaskScope;
  status: AgentTaskStatus;
  heading: ColumnHeading;
  agentName?: (agentId: string) => string | undefined;
  onOpen: (task: AgentTaskSummary) => void;
}) {
  const { tasks, total, isLoading, error, refetch, hasMore, loadMore, isLoadingMore } = useTasks(scope, status);
  const label = TASK_STATUS_LABEL[status];

  return (
    <section
      aria-label={`${label} tasks`}
      className="flex flex-col rounded-xl p-2 sm:min-w-[15rem] sm:flex-1"
      style={{ background: "var(--bg-sunken)" }}
    >
      <Heading className="m-0 flex items-baseline gap-2 px-2 py-1.5 text-[0.84rem] font-semibold">
        {label}
        {!isLoading && !error && (
          <span className="text-[0.78rem] font-medium tabular-nums" style={{ color: "var(--ink-3)" }}>
            {total}
          </span>
        )}
      </Heading>
      {isLoading ? (
        <p role="status" className="m-0 px-2 py-2 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
          Loading tasks…
        </p>
      ) : error ? (
        <div className="p-1">
          <AppErrorState error={error} title="Could not load tasks" onRetry={() => void refetch()} />
        </div>
      ) : tasks.length === 0 ? (
        <p className="m-0 px-2 py-2 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
          No tasks.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {tasks.map((task) => (
            <li key={task.id}>
              <button
                type="button"
                data-testid="task-card"
                className={`af-card af-card-hover block w-full px-3 py-2.5 text-left ${TASK_FOCUS_RING}`}
                onClick={() => onOpen(task)}
              >
                <span className="block text-[0.88rem] font-medium leading-snug">{task.title}</span>
                <TaskSummaryMeta task={task} agentName={agentName?.(task.agentId)} />
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

/**
 * Tasks in a column per status, each card opening its notes and files. Columns sit side by
 * side from small screens up, and stack on a phone.
 */
export function TaskBoard({
  scope,
  emptyMessage,
  columnHeading,
  agentName,
  onOpen,
}: {
  scope: TaskScope;
  /** Shown once in place of the columns when there are no Tasks at all. */
  emptyMessage: string;
  /** The level that fits under the page's own heading. */
  columnHeading: ColumnHeading;
  /** Names each Task's Agent, on boards that span Agents. */
  agentName?: (agentId: string) => string | undefined;
  onOpen: (task: AgentTaskSummary) => void;
}) {
  // Shares its cache with the unfiltered list, so switching views costs no extra request.
  const everything = useTasks(scope, null);
  if (!everything.isLoading && !everything.error && everything.total === 0) {
    return (
      <div role="status" className="af-card px-5 py-4 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        {emptyMessage}
      </div>
    );
  }
  return (
    <div className="sm:overflow-x-auto">
      <div className="flex flex-col gap-3 pb-1 sm:flex-row sm:items-start">
        {TASK_STATUSES.map((status) => (
          <TaskBoardColumn
            key={status}
            scope={scope}
            status={status}
            heading={columnHeading}
            agentName={agentName}
            onOpen={onOpen}
          />
        ))}
      </div>
    </div>
  );
}
