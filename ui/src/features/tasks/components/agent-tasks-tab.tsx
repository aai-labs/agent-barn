"use client";

import { parseAsStringEnum, useQueryState } from "nuqs";

import type { Agent } from "@/features/agents/schemas";

import { useAgentTasks } from "../hooks/use-agent-tasks";
import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS } from "../utils";
import { TaskFilterSelect } from "./task-filter-select";
import { TaskList } from "./task-list";

/** Shown to people who may see the Agent's Tasks. */
export function AgentTasksTab({ agent }: { agent: Agent }) {
  const [status, setStatus] = useQueryState(
    "taskStatus",
    parseAsStringEnum<AgentTaskStatus>(TASK_STATUSES).withOptions({ history: "replace", scroll: false }),
  );
  const tasks = useAgentTasks(agent.id, status);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="m-0 text-[0.86rem]" style={{ color: "var(--ink-3)" }}>
          What {agent.name} has worked on, and the files it produced.
        </p>
        <TaskFilterSelect
          label="Status"
          allLabel="All statuses"
          value={status}
          options={TASK_STATUS_OPTIONS}
          onChange={(next) => void setStatus(next as AgentTaskStatus | null)}
        />
      </div>
      <TaskList
        {...tasks}
        emptyMessage={status ? "No tasks with this status." : "This Agent hasn't recorded any tasks yet."}
      />
    </div>
  );
}
