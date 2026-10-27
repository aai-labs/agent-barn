"use client";

import { parseAsString, parseAsStringEnum, useQueryStates } from "nuqs";

import { useAgents } from "@/features/agents/hooks/use-agents";
import { canAgent } from "@/features/agents/utils";

import { useOrganizationTasks } from "../hooks/use-agent-tasks";
import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS } from "../utils";
import { TaskFilterSelect } from "./task-filter-select";
import { TaskList } from "./task-list";

/** Tasks across every Agent whose Tasks the viewer can see. */
export function OrganizationTasksPage() {
  const [filters, setFilters] = useQueryStates(
    {
      agent: parseAsString,
      status: parseAsStringEnum<AgentTaskStatus>(TASK_STATUSES),
    },
    { history: "replace", scroll: false },
  );
  const { agents } = useAgents();
  const taskAgents = agents.filter((agent) => canAgent(agent, "task.read"));
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]));
  const tasks = useOrganizationTasks(filters.agent, filters.status);
  const isFiltered = filters.agent !== null || filters.status !== null;

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
        <div className="flex flex-wrap gap-3">
          <TaskFilterSelect
            label="Agent"
            allLabel="All agents"
            value={filters.agent}
            options={taskAgents.map((agent) => ({ value: agent.id, label: agent.name }))}
            onChange={(agent) => void setFilters({ agent })}
          />
          <TaskFilterSelect
            label="Status"
            allLabel="All statuses"
            value={filters.status}
            options={TASK_STATUS_OPTIONS}
            onChange={(status) => void setFilters({ status: status as AgentTaskStatus | null })}
          />
        </div>
      </div>
      <TaskList
        {...tasks}
        agentName={(agentId) => agentNames.get(agentId)}
        emptyMessage={isFiltered ? "No tasks match these filters." : "Your Agents haven't recorded any tasks yet."}
      />
    </div>
  );
}
