"use client";

import { useState } from "react";

import { api } from "@/shared/api";

import { AuditLogFilters, AuditScope, buildAuditParams } from "../utils";

/**
 * Downloads the audit log as CSV honoring the current filters. Fetches the file as a Blob
 * (so the auth + org headers are attached by the client interceptors), then triggers a
 * client-side download — the filename is set here, so we never need the server's
 * Content-Disposition header (which CORS would otherwise hide from JS).
 */
export function useAuditLogExport(scope: AuditScope) {
  const [isExporting, setIsExporting] = useState(false);

  async function exportCsv(filters: AuditLogFilters) {
    setIsExporting(true);
    try {
      const params = buildAuditParams(scope, filters);
      const response = await api.getFile(
        `/api/v1/audit-logs/export?${params.toString()}`,
      );
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `audit-logs-${new Date().toISOString().split("T")[0]}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setIsExporting(false);
    }
  }

  return { exportCsv, isExporting };
}
