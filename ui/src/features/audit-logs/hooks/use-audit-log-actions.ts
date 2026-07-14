"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { AuditActionsSchema } from "../schemas";
import { auditLogsKey } from "../utils";

/**
 * The full catalog of audit action codes (from the backend enum), for the filter
 * dropdown. Static over a session, so it's cached aggressively.
 */
export function useAuditLogActions() {
  const query = useQuery({
    queryKey: auditLogsKey.detail("actions"),
    queryFn: async () => {
      const response = await api.get<string[]>("/api/v1/audit-logs/actions", {
        schema: AuditActionsSchema,
      });
      return response.data;
    },
    staleTime: 60 * 60 * 1000,
  });

  return { actions: query.data ?? [] };
}
