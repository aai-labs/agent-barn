"use client";

import { parseAsString, parseAsStringEnum, useQueryStates } from "nuqs";

import { AppErrorState } from "@/components/app-error-state";
import { DateRangePicker } from "@/components/date-range-picker";
import { useAllAgents } from "@/features/agents/hooks/use-all-agents";
import { canAgent } from "@/features/agents/utils";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useTasks } from "../hooks/use-agent-tasks";
import { useOpenTask } from "../hooks/use-open-task";
import type { AgentTaskStatus } from "../schemas";
import {
  DEFAULT_TASK_WINDOW_LABEL,
  isUuid,
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

const EMPTY = "Your Agents haven't recorded any tasks yet.";

/** Tasks across every Agent whose Tasks the viewer can see. */
export function OrganizationTasksPage() {
  const [filters, setFilters] = useQueryStates(
    {
      agent: parseAsString,
      status: parseAsStringEnum<AgentTaskStatus>(TASK_STATUSES),
      view: parseAsStringEnum<TaskView>(TASK_VIEWS).withDefault("board"),
      from: parseAsString,
      to: parseAsString,
    },
    { history: "replace", scroll: false },
  );
  const [openTask, setOpenTask] = useOpenTask();
  const { selectedOrganization } = useOrganizationContext();
  const { agents, error: agentsError, refetch: refetchAgents } = useAllAgents();
  const taskAgents = agents.filter((agent) => canAgent(agent, "task.read"));
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]));
  const agentFilter = isUuid(filters.agent) ? filters.agent : null;
  const scope = { kind: "organization", agentId: agentFilter } as const;
  const dates = taskWindow(filters.from, filters.to);
  // Shared with the board's empty check: whether there are any Tasks at all.
  const recordedAny = useTasks(scope, null).total > 0;
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
            value={agentFilter}
            options={taskAgents.map((agent) => ({ value: agent.id, label: agent.name }))}
            onChange={(agent) => void setFilters({ agent })}
          />
          <DateRangePicker
            from={filters.from ?? ""}
            to={filters.to ?? ""}
            onChange={(from, to) => void setFilters({ from: from || null, to: to || null })}
            placeholder={DEFAULT_TASK_WINDOW_LABEL}
            width="16rem"
            ariaLabel="Date range"
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
      {/* Tasks still load without their Agents' names; say so rather than show them unnamed. */}
      {agentsError && (
        <div className="mb-4">
          <AppErrorState
            error={agentsError}
            title="Could not load your Agents"
            onRetry={() => void refetchAgents()}
          />
        </div>
      )}
      {filters.view === "board" ? (
        <TaskBoard
          scope={scope}
          dates={dates}
          emptyMessage={agentFilter ? "This Agent hasn't recorded any tasks yet." : EMPTY}
          columnHeading="h2"
          agentName={agentName}
          onOpen={open}
        />
      ) : (
        <TaskList
          scope={scope}
          status={filters.status}
          dates={dates}
          agentName={agentName}
          emptyMessage={
            agentFilter || filters.status
              ? "No tasks match these filters."
              : recordedAny
                ? windowEmptyMessage(dates.picked)
                : EMPTY
          }
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
