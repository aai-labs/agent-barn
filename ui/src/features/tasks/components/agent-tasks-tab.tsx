"use client";

import { parseAsString, parseAsStringEnum, useQueryState, useQueryStates } from "nuqs";

import { DateRangePicker } from "@/components/date-range-picker";

import type { Agent } from "@/features/agents/schemas";

import { useTasks } from "../hooks/use-agent-tasks";
import { useOpenTask } from "../hooks/use-open-task";
import type { AgentTaskStatus } from "../schemas";
import {
  DEFAULT_TASK_WINDOW_LABEL,
  taskWindow,
  TASK_STATUSES,
  TASK_STATUS_OPTIONS,
  TASK_VIEWS,
  windowEmptyMessage,
  type TaskView,
} from "../utils";
import { TaskBoard } from "./task-board";
import { TaskDetailDialog } from "./task-detail-dialog";
import { TaskFilterSelect } from "./task-filter-select";
import { TaskList } from "./task-list";
import { TaskViewToggle } from "./task-view-toggle";

const EMPTY = "This Agent hasn't recorded any tasks yet.";

/** Shown to people who may see the Agent's Tasks. */
export function AgentTasksTab({ agent }: { agent: Agent }) {
  const [view, setView] = useQueryState(
    "taskView",
    parseAsStringEnum<TaskView>(TASK_VIEWS).withDefault("board").withOptions({ history: "replace", scroll: false }),
  );
  const [status, setStatus] = useQueryState(
    "taskStatus",
    parseAsStringEnum<AgentTaskStatus>(TASK_STATUSES).withOptions({ history: "replace", scroll: false }),
  );
  const [range, setRange] = useQueryStates(
    { taskFrom: parseAsString, taskTo: parseAsString },
    { history: "replace", scroll: false },
  );
  const [openTask, setOpenTask] = useOpenTask();
  const scope = { kind: "agent", agentId: agent.id } as const;
  const dates = taskWindow(range.taskFrom, range.taskTo);
  // Shared with the board's empty check: whether the Agent has recorded anything at all.
  const recordedAny = useTasks(scope, null).total > 0;
  const open = (task: { agentId: string; id: string }) => setOpenTask({ agentId: task.agentId, taskId: task.id });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 text-[0.86rem]" style={{ color: "var(--ink-3)" }}>
          What {agent.name} has worked on, and the files it produced.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <DateRangePicker
            from={range.taskFrom ?? ""}
            to={range.taskTo ?? ""}
            onChange={(from, to) => void setRange({ taskFrom: from || null, taskTo: to || null })}
            placeholder={DEFAULT_TASK_WINDOW_LABEL}
            width="16rem"
            ariaLabel="Date range"
          />
          {/* The board's columns already split Tasks by status. */}
          {view === "list" && (
            <TaskFilterSelect
              label="Status"
              allLabel="All statuses"
              value={status}
              options={TASK_STATUS_OPTIONS}
              onChange={(next) => void setStatus(next as AgentTaskStatus | null)}
            />
          )}
          <TaskViewToggle
            value={view}
            onChange={(next) => {
              void setView(next);
              // The board has no status filter, so one left over must not narrow the list later.
              if (next === "board") void setStatus(null);
            }}
          />
        </div>
      </div>
      {view === "board" ? (
        <TaskBoard scope={scope} dates={dates} emptyMessage={EMPTY} columnHeading="h3" onOpen={open} />
      ) : (
        <TaskList
          scope={scope}
          status={status}
          dates={dates}
          emptyMessage={
            status ? "No tasks with this status." : recordedAny ? windowEmptyMessage(dates.picked) : EMPTY
          }
          onOpen={open}
        />
      )}
      <TaskDetailDialog openTask={openTask} onClose={() => setOpenTask(null)} />
    </div>
  );
}
