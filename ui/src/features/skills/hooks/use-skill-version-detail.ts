"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "@/shared/api";

import { SkillFileSchema, SkillVersionSchema, type SkillFile, type SkillVersion } from "../schemas";
import { useSkillsBasePath, type SkillScopeRef } from "../scope";
import { skillVersionKey } from "../utils";

const SkillVersionDetailSchema = SkillVersionSchema.extend({ files: z.array(SkillFileSchema) });
type SkillVersionDetail = SkillVersion & { files: SkillFile[] };

/** A single published version's files, for read-only viewing of history. */
export function useSkillVersionDetail(skillId: string | null, version: number | null, scope: SkillScopeRef) {
  const basePath = useSkillsBasePath(scope);

  const query = useQuery({
    queryKey: skillVersionKey(skillId ?? "none", version ?? 0, scope),
    enabled: skillId !== null && version !== null,
    queryFn: async () => {
      const response = await api.get<SkillVersionDetail>(`${basePath}/${skillId}/versions/${version}`, {
        schema: SkillVersionDetailSchema,
      });
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
