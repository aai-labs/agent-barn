"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useTemplatesBasePath } from "@/features/templates/scope";
import { templateDraftKey, templateLineagesKey } from "@/features/templates/utils";
import { api } from "@/shared/api";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { ConventionsAppliedSchema, type ConventionsApplied } from "../schemas";

const ORGANIZATION_TEMPLATES = { kind: "organization" } as const;

export type TemplateConventionsResult =
  | ({ ok: true } & ConventionsApplied)
  | { ok: false; templateKey: string; message: string };

/**
 * Add reviewed Organization Conventions to each chosen Template's draft AGENTS.md.
 * Templates are updated one by one so one refusal does not block the others;
 * publishing each draft stays with the person.
 */
export function useAddConventionsToTemplates() {
  const basePath = useTemplatesBasePath(ORGANIZATION_TEMPLATES);
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ rules, templateKeys }: { rules: string[]; templateKeys: string[] }) => {
      const results: TemplateConventionsResult[] = [];
      for (const templateKey of templateKeys) {
        try {
          const response = await api.post<ConventionsApplied>(
            `${basePath}/${templateKey}/draft/conventions`,
            { rules },
            { schema: ConventionsAppliedSchema },
          );
          results.push({ ok: true, ...response.data });
        } catch (caught) {
          results.push({ ok: false, templateKey, message: getErrorDisplay(caught).description });
        }
      }
      return results;
    },
    onSettled: async (_results, _error, { templateKeys }) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: templateLineagesKey(ORGANIZATION_TEMPLATES) }),
        ...templateKeys.map((key) =>
          client.invalidateQueries({ queryKey: templateDraftKey(key, ORGANIZATION_TEMPLATES) }),
        ),
      ]);
    },
  });
}
