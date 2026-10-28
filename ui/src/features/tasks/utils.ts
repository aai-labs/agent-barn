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

const _tasksKeyBase = createQueryKeyStructure("agent-tasks");

/** Agent-level keys live under the Agent's detail family; Organization-level ones in their own,
 * evicted on an Organization switch and keyed by the Organization API base. */
export const tasksKey = {
  ..._tasksKeyBase,
  agentTasks: (agentId: string, orgApiBase: string, status: AgentTaskStatus | null) =>
    [...agentsKey.detail(agentId), "tasks", orgApiBase, status] as const,
  task: (agentId: string, orgApiBase: string, taskId: string) =>
    [...agentsKey.detail(agentId), "task", orgApiBase, taskId] as const,
  organizationTasks: (orgApiBase: string, agentId: string | null, status: AgentTaskStatus | null) =>
    [..._tasksKeyBase.all, orgApiBase, agentId, status] as const,
};

export function taskListParams(page: number, filter: { agentId?: string | null; status: AgentTaskStatus | null }) {
  const params = new URLSearchParams({ page: String(page), page_size: String(TASKS_PAGE_SIZE) });
  if (filter.agentId) params.set("agent_id", filter.agentId);
  if (filter.status) params.set("status", filter.status);
  return params.toString();
}
