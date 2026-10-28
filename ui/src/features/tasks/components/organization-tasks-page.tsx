"use client";

import { parseAsString, parseAsStringEnum, useQueryStates } from "nuqs";

import { useAgents } from "@/features/agents/hooks/use-agents";
import { canAgent } from "@/features/agents/utils";

import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS, TASK_VIEWS, type TaskView } from "../utils";
import { TaskBoard } from "./task-board";
import { TaskFilterSelect } from "./task-filter-select";
import { ScopedTaskList } from "./task-list";
import { TaskViewToggle } from "./task-view-toggle";

/** Tasks across every Agent whose Tasks the viewer can see. */
export function OrganizationTasksPage() {
  const [filters, setFilters] = useQueryStates(
    {
      agent: parseAsString,
      status: parseAsStringEnum<AgentTaskStatus>(TASK_STATUSES),
      view: parseAsStringEnum<TaskView>(TASK_VIEWS).withDefault("board"),
    },
    { history: "replace", scroll: false },
  );
  const { agents } = useAgents();
  const taskAgents = agents.filter((agent) => canAgent(agent, "task.read"));
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]));
  const scope = { kind: "organization", agentId: filters.agent } as const;
  const isFiltered = filters.agent !== null || filters.status !== null;
  const agentName = (agentId: string) => agentNames.get(agentId);

  return (
    <div>
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="m-0 mb-1 text-[28px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Tasks
          </h1>
          <p className="m-0 text-[14px]" style={{ color: "var(--ink-3)" }}>
            What your Agents have worked on, and the files they produced.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <TaskFilterSelect
            label="Agent"
            allLabel="All agents"
            value={filters.agent}
            options={taskAgents.map((agent) => ({ value: agent.id, label: agent.name }))}
            onChange={(agent) => void setFilters({ agent })}
          />
          {/* The board's columns already split Tasks by status. */}
          {filters.view === "list" && (
            <TaskFilterSelect
              label="Status"
              allLabel="All statuses"
              value={filters.status}
              options={TASK_STATUS_OPTIONS}
              onChange={(status) => void setFilters({ status: status as AgentTaskStatus | null })}
            />
          )}
          <TaskViewToggle value={filters.view} onChange={(view) => void setFilters({ view })} />
        </div>
      </div>
      {filters.view === "board" ? (
        <TaskBoard scope={scope} agentName={agentName} />
      ) : (
        <ScopedTaskList
          scope={scope}
          status={filters.status}
          agentName={agentName}
          emptyMessage={isFiltered ? "No tasks match these filters." : "Your Agents haven't recorded any tasks yet."}
        />
      )}
    </div>
  );
}
