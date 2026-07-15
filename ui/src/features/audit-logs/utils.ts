import { createQueryKeyStructure } from "@/shared/query-keys";

export const AUDIT_PAGE_SIZE = 25;
export const auditLogsKey = createQueryKeyStructure("audit-logs");

export type AuditLogFilters = {
  action?: string;
  search?: string;
  startDate?: string;
  endDate?: string;
  organizationId?: string;
};

export type AuditScope = "org" | "all";

/**
 * Build the shared query string for the list and export endpoints. ``scope`` and
 * ``organizationId`` are only honored server-side for superusers; sending them for an
 * org admin is harmless (the API overrides them to the caller's own org).
 */
export function buildAuditParams(
  scope: AuditScope,
  filters: AuditLogFilters,
): URLSearchParams {
  const params = new URLSearchParams();
  if (scope === "all") {
    params.set("scope", "all");
  } else if (filters.organizationId) {
    params.set("organization_id", filters.organizationId);
  }
  if (filters.action) params.set("action", filters.action);
  if (filters.search) params.set("search", filters.search);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  return params;
}

/**
 * Turn a dotted action code ("agent.create") into a readable label ("Agent created").
 * Falls back to a humanized version of the raw code for actions with no explicit label.
 */
export function formatAction(action: string): string {
  return ACTION_LABELS[action] ?? humanizeAction(action);
}

function humanizeAction(action: string): string {
  const withoutDomain = action.includes(".")
    ? action.slice(action.indexOf(".") + 1)
    : action;
  const words = withoutDomain.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const ACTION_LABELS: Record<string, string> = {
  "agent.create": "Agent created",
  "agent.update": "Agent updated",
  "agent.start": "Agent started",
  "agent.stop": "Agent stopped",
  "agent.delete": "Agent deleted",
  "agent.view": "Viewed agent",
  "agent.logs_view": "Viewed agent logs",
  "agent.conversations_view": "Viewed conversations",
  "agent.tool_calls_view": "Viewed tool calls",
  "org.create": "Organization created",
  "org.update": "Organization updated",
  "org.delete": "Organization deleted",
  "member.add": "Member added",
  "member.role_change": "Member role changed",
  "member.remove": "Member removed",
  "member.ownership_transfer": "Ownership transferred",
  "member.invite_resend": "Invite resent",
  "template.create": "Template created",
  "template.update": "Template updated",
  "skill.create": "Skill created",
  "skill.update": "Skill updated",
  "skill.delete": "Skill deleted",
  "user.create": "User created",
  "user.password_reset": "User password reset",
  "user.delete": "User deleted",
  "auth.login": "Logged in",
  "auth.login_failed": "Failed login",
  "auth.logout": "Logged out",
  "auth.password_change": "Password changed",
  "auth.password_reset_request": "Password reset requested",
  "auth.password_reset": "Password reset",
  "auth.set_password": "Password set",
  "auth.slack_config_token_save": "Slack config token saved",
  "auth.slack_config_token_delete": "Slack config token deleted",
  "integration.google_connect": "Google connected",
  "integration.slack_app_create": "Slack app created",
  "cost.view": "Viewed costs",
  "audit_log.view": "Viewed audit log",
  "audit_log.export": "Exported audit log",
};
