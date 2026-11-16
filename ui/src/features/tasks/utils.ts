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

/** With no dates picked, lists and boards show the last 30 days. Boards would otherwise fill up
 * with old finished work, whose files have usually expired. */
/** Bounds on a Task's last change, both inclusive; null is open-ended. */
export type TaskWindow = { since: string | null; before: string | null };
export const NO_TASK_WINDOW: TaskWindow = { since: null, before: null };

export const DEFAULT_TASK_DAYS = 30;
export const DEFAULT_TASK_WINDOW_LABEL = `Last ${DEFAULT_TASK_DAYS} days`;

/** The bounds a list asks for. Unset dates count from midnight, so the time, and the lists'
 * cache keys, hold for the day. */
export function taskWindow(from: string | null, to: string | null) {
  if (from || to) return { since: from || null, before: to || null, picked: true };
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - DEFAULT_TASK_DAYS);
  return { since: start.toISOString(), before: null, picked: false };
}

export function windowEmptyMessage(picked: boolean): string {
  return picked ? "No tasks in these dates." : `No tasks in the last ${DEFAULT_TASK_DAYS} days.`;
}

/** Unfinished Tasks stay on the board whatever their age; the period trims finished ones. */
export const FINISHED_TASK_STATUSES: AgentTaskStatus[] = ["done", "failed"];

const _tasksKeyBase = createQueryKeyStructure("agent-tasks");

/** Agent-level keys live under the Agent's detail family; Organization-level ones in their own,
 * evicted on an Organization switch and keyed by the Organization API base. */
export const tasksKey = {
  ..._tasksKeyBase,
  agentTasks: (agentId: string, orgApiBase: string, status: AgentTaskStatus | null, dates: TaskWindow) =>
    [...agentsKey.detail(agentId), "tasks", orgApiBase, status, dates.since, dates.before] as const,
  task: (agentId: string, orgApiBase: string, taskId: string) =>
    [...agentsKey.detail(agentId), "task", orgApiBase, taskId] as const,
  organizationTasks: (
    orgApiBase: string,
    agentId: string | null,
    status: AgentTaskStatus | null,
    dates: TaskWindow,
  ) => [..._tasksKeyBase.all, orgApiBase, agentId, status, dates.since, dates.before] as const,
};

export function taskListParams(
  page: number,
  filter: { agentId?: string | null; status: AgentTaskStatus | null; dates?: TaskWindow },
) {
  const params = new URLSearchParams({ page: String(page), page_size: String(TASKS_PAGE_SIZE) });
  if (filter.agentId) params.set("agent_id", filter.agentId);
  if (filter.status) params.set("status", filter.status);
  if (filter.dates?.since) params.set("updated_since", filter.dates.since);
  if (filter.dates?.before) params.set("updated_before", filter.dates.before);
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
