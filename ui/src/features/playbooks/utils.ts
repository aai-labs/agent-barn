import { agentsKey } from "@/features/agents/utils";
import { createQueryKeyStructure } from "@/shared/query-keys";

import type { PlaybookExtraction, PlaybookExtractionError, PlaybookExtractionStatus } from "./schemas";

export const PLAYBOOK_RUNS_PAGE_SIZE = 20;
export const ACTIVE_STATUSES: ReadonlySet<PlaybookExtractionStatus> = new Set(["QUEUED", "RUNNING"]);

export const WINDOW_DAY_OPTIONS = [7, 30, 90] as const;
export const MAX_SESSION_OPTIONS = [10, 20, 50] as const;

const _playbookRunsKeyBase = createQueryKeyStructure("playbook-extractions");

/** Agent-level keys live under the Agent's detail family; Organization-level ones in their own,
 * evicted on an Organization switch and keyed by the Organization API base. */
export const playbooksKey = {
  ..._playbookRunsKeyBase,
  agentRuns: (agentId: string) => [...agentsKey.detail(agentId), "playbook-extractions"] as const,
  agentRunsPage: (agentId: string, orgApiBase: string, page: number) =>
    [...agentsKey.detail(agentId), "playbook-extractions", orgApiBase, page] as const,
  run: (agentId: string, runId: string) => [...agentsKey.detail(agentId), "playbook-extraction", runId] as const,
  preview: (agentId: string, orgApiBase: string, windowDays: number, maxSessions: number) =>
    [...agentsKey.detail(agentId), "playbook-preview", orgApiBase, windowDays, maxSessions] as const,
  organizationRuns: (orgApiBase: string, skillId: string | null) =>
    [..._playbookRunsKeyBase.all, orgApiBase, skillId] as const,
  platformSettings: () => ["platform-playbook-settings", "settings"] as const,
  platformModels: () => ["platform-playbook-settings", "models"] as const,
};

export function isActive(run: Pick<PlaybookExtraction, "status">): boolean {
  return ACTIVE_STATUSES.has(run.status);
}

export const STATUS_LABEL: Record<PlaybookExtractionStatus, string> = {
  QUEUED: "Queued",
  RUNNING: "Running",
  SUCCEEDED: "Ready to review",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

const ERROR_MESSAGE: Record<PlaybookExtractionError, string> = {
  enqueue_failed: "The run could not be started. Try again.",
  requester_lost_access: "The person who started this run no longer has access to this Agent or to Skills.",
  source_agent_unavailable: "The Agent was deleted before the run started.",
  no_sessions: "There were no conversations in the selected period.",
  model_unavailable: "The model or this Agent's model key was rejected.",
  spend_limit_reached: "The Agent's or Organization's spend limit was reached.",
  model_error: "The model failed or answered in an unexpected shape. Try again.",
  answer_truncated:
    "The model's answer was longer than allowed and was cut off. Try again, or read fewer conversations.",
  draft_conflict:
    "The playbook already had an unpublished draft, which was left untouched. The generated playbook is kept on this run.",
  skill_unavailable: "The target Skill can no longer receive playbooks.",
  interrupted:
    "The run was stopped before it finished: it ran past its time limit or its worker restarted. Model calls already made are still billed. Try again.",
  internal_error: "Something went wrong. Try again.",
};

export function errorMessage(code: string | null): string | null {
  if (code === null) return null;
  return ERROR_MESSAGE[code as PlaybookExtractionError] ?? "The run failed.";
}
