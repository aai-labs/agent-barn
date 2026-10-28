"use client";

import { parseAsString, parseAsStringEnum, useQueryStates } from "nuqs";

import { useAgents } from "@/features/agents/hooks/use-agents";
import { canAgent } from "@/features/agents/utils";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useOpenTask } from "../hooks/use-open-task";
import type { AgentTaskStatus } from "../schemas";
import { TASK_STATUSES, TASK_STATUS_OPTIONS, TASK_VIEWS, type TaskView } from "../utils";
import { TaskBoard } from "./task-board";
import { TaskDetailDialog } from "./task-detail-dialog";
import { TaskFilterSelect } from "./task-filter-select";
import { TaskList } from "./task-list";
import { TaskViewToggle } from "./task-view-toggle";

const EMPTY = "Your Agents haven't recorded any tasks yet.";

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
  const [openTask, setOpenTask] = useOpenTask();
  const { selectedOrganization } = useOrganizationContext();
  const { agents } = useAgents();
  const taskAgents = agents.filter((agent) => canAgent(agent, "task.read"));
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]));
  const scope = { kind: "organization", agentId: filters.agent } as const;
  const agentName = (agentId: string) => agentNames.get(agentId);
  const open = (task: { agentId: string; id: string }) => setOpenTask({ agentId: task.agentId, taskId: task.id });

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
          {/* The board has no status filter, so one left over must not narrow the list later. */}
          <TaskViewToggle
            value={filters.view}
            onChange={(view) => void setFilters(view === "board" ? { view, status: null } : { view })}
          />
        </div>
      </div>
      {filters.view === "board" ? (
        <TaskBoard
          scope={scope}
          emptyMessage={filters.agent ? "This Agent hasn't recorded any tasks yet." : EMPTY}
          columnHeading="h2"
          agentName={agentName}
          onOpen={open}
        />
      ) : (
        <TaskList
          scope={scope}
          status={filters.status}
          agentName={agentName}
          emptyMessage={filters.agent || filters.status ? "No tasks match these filters." : EMPTY}
          onOpen={open}
        />
      )}
      <TaskDetailDialog
        openTask={openTask}
        onClose={() => setOpenTask(null)}
        agentName={openTask ? agentName(openTask.agentId) : undefined}
        agentHref={
          openTask && selectedOrganization
            ? `/dashboard/${selectedOrganization.id}/agents/${openTask.agentId}?tab=tasks`
            : undefined
        }
      />
    </div>
  );
}
