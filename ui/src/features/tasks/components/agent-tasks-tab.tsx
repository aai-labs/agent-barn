"use client";

import { parseAsStringEnum, useQueryState } from "nuqs";

import type { Agent } from "@/features/agents/schemas";

import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS, TASK_VIEWS, type TaskView } from "../utils";
import { TaskBoard } from "./task-board";
import { TaskFilterSelect } from "./task-filter-select";
import { ScopedTaskList } from "./task-list";
import { TaskViewToggle } from "./task-view-toggle";

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
  const scope = { kind: "agent", agentId: agent.id } as const;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
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
          <TaskViewToggle value={view} onChange={(next) => void setView(next)} />
        </div>
      </div>
      {view === "board" ? (
        <TaskBoard scope={scope} />
      ) : (
        <ScopedTaskList
          scope={scope}
          status={status}
          emptyMessage={status ? "No tasks with this status." : "This Agent hasn't recorded any tasks yet."}
        />
      )}
    </div>
  );
}
