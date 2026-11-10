import { agentsKey } from "@/features/agents/utils";
import { createQueryKeyStructure } from "@/shared/query-keys";

import type { AgentTaskStatus } from "./schemas";

export const TASKS_PAGE_SIZE = 20;

export type TaskView = "board" | "list";
export const TASK_VIEWS: TaskView[] = ["board", "list"];

export const TASK_STATUSES: AgentTaskStatus[] = ["open", "in_progress", "done", "failed"];

export const TASK_STATUS_LABEL: Record<AgentTaskStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  done: "Done",
  failed: "Failed",
};

export const TASK_STATUS_OPTIONS = TASK_STATUSES.map((status) => ({ value: status, label: TASK_STATUS_LABEL[status] }));

/** How far back lists and boards look, by a Task's last change. Boards would otherwise fill up
 * with old finished work, whose files have usually expired. */
export type TaskPeriod = "7d" | "30d" | "all";
export const TASK_PERIODS: TaskPeriod[] = ["7d", "30d", "all"];
export const DEFAULT_TASK_PERIOD: TaskPeriod = "30d";
const PERIOD_DAYS: Record<Exclude<TaskPeriod, "all">, number> = { "7d": 7, "30d": 30 };
export const TASK_PERIOD_OPTIONS = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

/** When a period starts: from midnight, so the time, and the lists' cache keys, hold for the day. */
export function periodStart(period: TaskPeriod): string | null {
  if (period === "all") return null;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - PERIOD_DAYS[period]);
  return start.toISOString();
}

export function periodEmptyMessage(period: TaskPeriod): string {
  return `No tasks in the last ${PERIOD_DAYS[period as Exclude<TaskPeriod, "all">]} days.`;
}

/** Unfinished Tasks stay on the board whatever their age; the period trims finished ones. */
export const FINISHED_TASK_STATUSES: AgentTaskStatus[] = ["done", "failed"];

const _tasksKeyBase = createQueryKeyStructure("agent-tasks");

/** Agent-level keys live under the Agent's detail family; Organization-level ones in their own,
 * evicted on an Organization switch and keyed by the Organization API base. */
export const tasksKey = {
  ..._tasksKeyBase,
  agentTasks: (agentId: string, orgApiBase: string, status: AgentTaskStatus | null, since: string | null) =>
    [...agentsKey.detail(agentId), "tasks", orgApiBase, status, since] as const,
  task: (agentId: string, orgApiBase: string, taskId: string) =>
    [...agentsKey.detail(agentId), "task", orgApiBase, taskId] as const,
  organizationTasks: (
    orgApiBase: string,
    agentId: string | null,
    status: AgentTaskStatus | null,
    since: string | null,
  ) => [..._tasksKeyBase.all, orgApiBase, agentId, status, since] as const,
};

export function taskListParams(
  page: number,
  filter: { agentId?: string | null; status: AgentTaskStatus | null; since?: string | null },
) {
  const params = new URLSearchParams({ page: String(page), page_size: String(TASKS_PAGE_SIZE) });
  if (filter.agentId) params.set("agent_id", filter.agentId);
  if (filter.status) params.set("status", filter.status);
  if (filter.since) params.set("updated_since", filter.since);
  return params.toString();
}

/** The open Task, kept in the URL as `<agentId>.<taskId>` so it can be linked to and Back closes it. */
export type OpenTask = { agentId: string; taskId: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Ids from the URL, which anyone can edit: anything that isn't one is ignored rather than sent. */
export function isUuid(value: string | null): value is string {
  return value !== null && UUID.test(value);
}

export function parseOpenTask(value: string | null): OpenTask | null {
  const [agentId, taskId, ...rest] = value?.split(".") ?? [];
  return isUuid(agentId ?? null) && isUuid(taskId ?? null) && rest.length === 0
    ? { agentId: agentId!, taskId: taskId! }
    : null;
}

export function serializeOpenTask(task: OpenTask | null): string | null {
  return task ? `${task.agentId}.${task.taskId}` : null;
}
