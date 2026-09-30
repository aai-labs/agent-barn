"use client";

import type { SkillScopeRef } from "@/features/skills/scope";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

export type TemplateScopeRef = { kind: "platform" } | { kind: "organization" };

export function templateScopeCacheKey(scope: TemplateScopeRef): string {
  return scope.kind;
}

export function useTemplatesBasePath(scope: TemplateScopeRef): string {
  const { selectedOrganization } = useOrganizationContext();
  if (scope.kind === "platform") return "/api/v1/platform/templates";
  if (!selectedOrganization) {
    throw new Error("No active organization is available for an organization-scoped Template request");
  }
  return `/api/v1/organizations/${selectedOrganization.id}/templates`;
}

export function useTemplateSkillsBasePath(scope: TemplateScopeRef): string {
  const { selectedOrganization } = useOrganizationContext();
  if (scope.kind === "platform") return "/api/v1/platform/skills";
  if (!selectedOrganization) {
    throw new Error("No active organization is available for an organization-scoped Skill request");
  }
  return `/api/v1/organizations/${selectedOrganization.id}/skills`;
}

export function templatesListHref(scope: TemplateScopeRef, orgId: string | null): string {
  if (scope.kind === "platform") return "/dashboard/platform/templates";
  if (!orgId) return "/dashboard";
  return `/dashboard/${orgId}/settings?tab=templates`;
}

export function templateDetailHref(
  scope: TemplateScopeRef,
  orgId: string | null,
  templateKey: string,
): string {
  if (scope.kind === "platform") return `/dashboard/platform/templates/${templateKey}`;
  if (!orgId) return "/dashboard";
  return `/dashboard/${orgId}/settings/templates/${templateKey}`;
}

export function templateNewHref(scope: TemplateScopeRef, orgId: string | null): string {
  if (scope.kind === "platform") return "/dashboard/platform/templates/new";
  if (!orgId) return "/dashboard";
  return `/dashboard/${orgId}/settings/templates/new`;
}

export function templateSkillScope(scope: TemplateScopeRef): SkillScopeRef {
  return scope.kind === "platform" ? { kind: "platform" } : { kind: "organization" };
}
