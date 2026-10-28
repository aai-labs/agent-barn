"use client";

import { parseAsStringEnum, useQueryState } from "nuqs";

import type { Agent } from "@/features/agents/schemas";

import { useOpenTask } from "../hooks/use-open-task";
import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS, TASK_VIEWS, type TaskView } from "../utils";
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
  const [openTask, setOpenTask] = useOpenTask();
  const scope = { kind: "agent", agentId: agent.id } as const;
  const open = (task: { agentId: string; id: string }) => setOpenTask({ agentId: task.agentId, taskId: task.id });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 text-[0.86rem]" style={{ color: "var(--ink-3)" }}>
          What {agent.name} has worked on, and the files it produced.
        </p>
        <div className="flex flex-wrap items-end gap-3">
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
        <TaskBoard scope={scope} emptyMessage={EMPTY} columnHeading="h3" onOpen={open} />
      ) : (
        <TaskList
          scope={scope}
          status={status}
          emptyMessage={status ? "No tasks with this status." : EMPTY}
          onOpen={open}
        />
      )}
      <TaskDetailDialog openTask={openTask} onClose={() => setOpenTask(null)} />
    </div>
  );
}
