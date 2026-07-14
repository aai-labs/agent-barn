"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { PaginatedAuditLogs, PaginatedAuditLogsSchema } from "../schemas";
import {
  AUDIT_PAGE_SIZE,
  AuditLogFilters,
  AuditScope,
  auditLogsKey,
  buildAuditParams,
} from "../utils";

type UseAuditLogsOptions = {
  scope: AuditScope;
  filters: AuditLogFilters;
  page: number;
};

export function useAuditLogs({ scope, filters, page }: UseAuditLogsOptions) {
  const query = useQuery({
    queryKey: auditLogsKey.list({
      scope: { scope },
      filters: { ...filters, page },
    }),
    queryFn: async () => {
      const params = buildAuditParams(scope, filters);
      params.set("page", String(page));
      params.set("page_size", String(AUDIT_PAGE_SIZE));

      const response = await api.get<PaginatedAuditLogs>(
        `/api/v1/audit-logs?${params.toString()}`,
        { schema: PaginatedAuditLogsSchema },
      );
      return response.data;
    },
    placeholderData: (previous) => previous,
  });

  return {
    logs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    pageSize: query.data?.pageSize ?? AUDIT_PAGE_SIZE,
    isLoading: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
