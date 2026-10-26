import type { BadgeVariant } from "@/components/badge";
import { agentsKey } from "@/features/agents/utils";

import type { AgentAddonKind, AgentAddonSpec, AgentAddonState } from "./schemas";

export const PLATFORM_AGENT_ADDONS_PAGE_SIZE = 50;

export const agentAddonsKey = {
  /** Under the Agent's own key, so switching Organization clears it with the Agent. */
  list: (agentId: string) => [...agentsKey.detail(agentId), "addons"] as const,
};

export const platformAgentAddonsKey = {
  /** Platform data: no Organization's cache is its. */
  all: ["platform", "agent-addons"] as const,
  list: (filters: { state: AgentAddonState | null; search: string; organizationId: string | null }) =>
    [...platformAgentAddonsKey.all, "list", filters] as const,
};

export const ADDON_KIND_LABELS: Record<AgentAddonKind, string> = {
  pip: "Python package",
  npm: "npm package",
  git: "Git repository",
  binary: "Binary download",
  command: "Install command",
};

export const ADDON_STATE_LABELS: Record<AgentAddonState, string> = {
  PENDING: "Pending review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
  REVOKED: "Revoked",
};

export const ADDON_STATE_VARIANTS: Record<AgentAddonState, BadgeVariant> = {
  PENDING: "warn",
  APPROVED: "ok",
  REJECTED: "danger",
  WITHDRAWN: "neutral",
  REVOKED: "neutral",
};

/** What gets installed, in one line: the package and its exact version, or the source and its pin. */
export function addonPin(kind: AgentAddonKind, name: string, spec: AgentAddonSpec): string {
  switch (kind) {
    case "pip":
      return `${name}==${spec.version ?? ""}`;
    case "npm":
      return `${name}@${spec.version ?? ""}`;
    case "git":
      return `${spec.url ?? ""} @ ${spec.commit ?? ""}`;
    case "binary":
      return `${spec.url ?? ""} (sha256 ${spec.sha256 ?? ""})`;
    case "command":
      return spec.command ?? "";
  }
}

export function formatAddonDate(value: string | null): string {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}
