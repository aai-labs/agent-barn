"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { SkillFileSchema, SkillVersionSchema, type SkillFile, type SkillVersion } from "../schemas";
import { skillVersionKey } from "../utils";

const SkillVersionDetailSchema = SkillVersionSchema.extend({ files: z.array(SkillFileSchema) });
type SkillVersionDetail = SkillVersion & { files: SkillFile[] };

/** A single published version's files, for read-only viewing of history. */
export function useSkillVersionDetail(skillId: string | null, version: number | null) {
  const orgApiBase = useOrganizationApiBase();

  const query = useQuery({
    queryKey: skillVersionKey(skillId ?? "none", version ?? 0),
    enabled: skillId !== null && version !== null,
    queryFn: async () => {
      const response = await api.get<SkillVersionDetail>(
        `${orgApiBase}/skills/${skillId}/versions/${version}`,
        { schema: SkillVersionDetailSchema },
      );
      return response.data;
    },
  });

  return {
    detail: query.data ?? null,
    files: query.data?.files ?? [],
    isLoading: query.isPending,
    error: query.error,
  };
}
