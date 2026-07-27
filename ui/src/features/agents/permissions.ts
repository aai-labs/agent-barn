import type { AgentAccessRoleRead, AgentPermissionKey } from "./schemas";

// Order controls display order in role capability summaries.
const PERMISSION_PHRASE: [AgentPermissionKey, string][] = [
  ["agent.read", "View"],
  ["agent.update", "Edit"],
  ["agent.lifecycle.manage", "Start/stop"],
  ["agent.secret.manage", "Manage secrets"],
  ["agent.delete", "Delete"],
  ["agent.access.manage", "Manage access"],
  ["activity.read", "See activity"],
  ["cost.read", "See costs"],
];

// Not exposed by the backend catalogue (AgentAccessRoleRead has no "sensitive" flag),
// so the set of permissions that warrant a warning before granting is defined here.
export const SENSITIVE_PERMISSIONS: AgentPermissionKey[] = [
  "agent.delete",
  "agent.access.manage",
];

const SENSITIVE_PHRASE: Record<string, string> = {
  "agent.delete": "delete this Agent",
  "agent.access.manage": "manage who has access to it",
};

export function sensitiveWarningText(role: Pick<AgentAccessRoleRead, "permissions">) {
  const phrases = SENSITIVE_PERMISSIONS.filter((p) => role.permissions.includes(p)).map(
    (p) => SENSITIVE_PHRASE[p],
  );
  if (phrases.length === 0) return null;
  return `Can ${phrases.join(" and ")}.`;
}

// Picks the least-privileged role as the default selection when granting new access —
// prefers a role with no sensitive permissions, falling back to the smallest grant.
export function defaultRoleId(roles: AgentAccessRoleRead[]): string | undefined {
  const byPermissionCount = [...roles].sort(
    (a, b) => a.permissions.length - b.permissions.length,
  );
  return (
    byPermissionCount.find((role) => !sensitiveWarningText(role))?.id ??
    byPermissionCount[0]?.id
  );
}

export function summarizeRolePermissions(permissions: AgentPermissionKey[]): string {
  const present = new Set(permissions);
  return PERMISSION_PHRASE.filter(([key]) => present.has(key))
    .map(([, phrase]) => phrase)
    .join(", ");
}
