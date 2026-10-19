"use client";

import { useQuery } from "@tanstack/react-query";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";
import { api } from "@/shared/api";

import { PaginatedPlaybookExtractionsSchema, type PaginatedPlaybookExtractions } from "../schemas";
import { playbooksKey } from "../utils";

const PAGE_SIZE = 100;

/**
 * The Organization's runs, optionally for one target Skill. Needs skill.manage, so
 * callers enable it only for Organization Owners and Admins.
 */
export function useOrganizationPlaybookRuns(skillId: string | null, enabled: boolean) {
  const orgApiBase = useOrganizationApiBase();
  const query = useQuery({
    queryKey: playbooksKey.organizationRuns(orgApiBase, skillId),
    queryFn: async () => {
      const params = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      if (skillId) params.set("skill_id", skillId);
      return (
        await api.get<PaginatedPlaybookExtractions>(`${orgApiBase}/playbook-extractions?${params.toString()}`, {
          schema: PaginatedPlaybookExtractionsSchema,
        })
      ).data;
    },
    enabled,
    retry: false,
  });
  return { runs: query.data?.items ?? [], isLoading: query.isPending && query.fetchStatus !== "idle", error: query.error };
}
