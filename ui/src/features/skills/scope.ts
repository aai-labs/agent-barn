"use client";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

/**
 * Which of the three Skill scopes a page/hook is operating in. Threading this
 * through the shared list/detail/new components and hooks — instead of forking
 * them per scope — is what lets Platform, Organization, and Agent skill
 * management share one implementation.
 */
export type SkillScopeRef =
  | { kind: "platform" }
  | { kind: "organization" }
  | { kind: "agent"; agentId: string };

/** A stable string for React Query keys and scope equality checks. */
export function skillScopeCacheKey(scope: SkillScopeRef): string {
  return scope.kind === "agent" ? `agent:${scope.agentId}` : scope.kind;
}

/**
 * The API base path for a scope's Skill routes. Platform Skills are a global
 * resource with no Organization in the path, so — unlike `useOrganizationApiBase`
 * — this only requires an active Organization for the other two scopes; a
 * Platform View page (no active Organization) can call this safely.
 */
export function useSkillsBasePath(scope: SkillScopeRef): string {
  const { selectedOrganization } = useOrganizationContext();
  if (scope.kind === "platform") return "/api/v1/platform/skills";
  if (!selectedOrganization) {
    throw new Error("No active organization is available for an organization- or agent-scoped Skill request");
  }
  const orgBase = `/api/v1/organizations/${selectedOrganization.id}`;
  return scope.kind === "agent" ? `${orgBase}/agents/${scope.agentId}/skills` : `${orgBase}/skills`;
}

/** Where a skill's own detail page lives when browsed from a given scope. */
export function skillDetailHref(scope: SkillScopeRef, orgId: string | null, skillId: string): string {
  if (scope.kind === "platform") return `/dashboard/platform/skills/${skillId}`;
  if (!orgId) return "/dashboard";
  return scope.kind === "agent"
    ? `/dashboard/${orgId}/agents/${scope.agentId}/skills/${skillId}`
    : `/dashboard/${orgId}/settings/skills/${skillId}`;
}

/** Where "New skill" lives for a given scope. */
export function skillNewHref(scope: SkillScopeRef, orgId: string | null): string {
  if (scope.kind === "platform") return "/dashboard/platform/skills/new";
  if (!orgId) return "/dashboard";
  return scope.kind === "agent"
    ? `/dashboard/${orgId}/agents/${scope.agentId}/skills/new`
    : `/dashboard/${orgId}/settings/skills/new`;
}

/** Where the "back to the list" link on a detail/new page should point. */
export function skillsListHref(scope: SkillScopeRef, orgId: string | null): string {
  if (scope.kind === "platform") return "/dashboard/platform/skills";
  if (!orgId) return "/dashboard";
  return scope.kind === "agent"
    ? `/dashboard/${orgId}/agents/${scope.agentId}/configuration?section=skills`
    : `/dashboard/${orgId}/settings?tab=skills`;
}

/**
 * Whether a skill visible from `viewingFrom` can be forked into that scope.
 * Platform is the root of the hierarchy (nothing to fork from); Organization
 * can only fork a Platform Skill; Agent can fork a Platform or Organization Skill.
 */
export function canForkInto(viewingFrom: SkillScopeRef, skillOwnScope: "platform" | "organization" | "agent"): boolean {
  if (viewingFrom.kind === "platform") return false;
  if (viewingFrom.kind === "organization") return skillOwnScope === "platform";
  return skillOwnScope === "platform" || skillOwnScope === "organization";
}
