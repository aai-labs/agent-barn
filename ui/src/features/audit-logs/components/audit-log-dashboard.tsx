"use client";

import React from "react";

import { AppErrorState } from "@/components/app-error-state";
import { useRequireOrgManager } from "@/features/organizations/hooks/use-require-org-manager";
import { useAllOrganizations } from "@/features/organizations/hooks/use-all-organizations";

import { useAuditLogActions } from "../hooks/use-audit-log-actions";
import { useAuditLogExport } from "../hooks/use-audit-log-export";
import { useAuditLogs } from "../hooks/use-audit-logs";
import { AUDIT_PAGE_SIZE, AuditLogFilters, AuditScope } from "../utils";
import { AuditLogFilters as FilterBar, DraftFilters } from "./audit-log-filters";
import { AuditLogTable } from "./audit-log-table";

const EMPTY: DraftFilters = {
  action: "",
  search: "",
  startDate: "",
  endDate: "",
  organizationId: "",
};

type Props = { scope: AuditScope };

export function AuditLogDashboard({ scope }: Props) {
  if (scope === "all") {
    return <AllOrgsDashboard />;
  }
  return <OrgDashboard />;
}

function OrgDashboard() {
  // Audit log is owner/admin-only; redirect a member who lands here.
  const canManage = useRequireOrgManager();
  const content = (
    <DashboardBody
      isAllOrgs={false}
      title="Audit log"
      subtitle="Who did what in this organization."
    />
  );
  return canManage ? content : null;
}

function AllOrgsDashboard() {
  const { organizations } = useAllOrganizations({ enabled: true });
  return (
    <DashboardBody
      isAllOrgs
      title="Audit log — all organizations"
      subtitle="Every organization's activity, plus global auth events."
      orgOptions={organizations.map((o) => ({ id: o.id, name: o.name }))}
    />
  );
}

function DashboardBody({
  isAllOrgs,
  title,
  subtitle,
  orgOptions,
}: {
  isAllOrgs: boolean;
  title: string;
  subtitle: string;
  orgOptions?: { id: string; name: string }[];
}) {
  const [applied, setApplied] = React.useState<DraftFilters>(EMPTY);
  const [page, setPage] = React.useState(1);
  const { actions } = useAuditLogActions();

  // In the all-orgs view, picking a specific org narrows to it; "All organizations"
  // (empty) requests every org. In the org view, scope is always the caller's own org.
  const effectiveScope: AuditScope =
    isAllOrgs && !applied.organizationId ? "all" : "org";

  const filters: AuditLogFilters = {
    action: applied.action || undefined,
    search: applied.search || undefined,
    startDate: applied.startDate || undefined,
    endDate: applied.endDate || undefined,
    organizationId: applied.organizationId || undefined,
  };

  const { logs, total, pageSize, isLoading, error, refetch } = useAuditLogs({
    scope: effectiveScope,
    filters,
    page,
  });
  const { exportCsv, isExporting } = useAuditLogExport(effectiveScope);

  const totalPages = Math.max(1, Math.ceil(total / (pageSize || AUDIT_PAGE_SIZE)));

  const onApply = (next: DraftFilters) => {
    setApplied(next);
    setPage(1);
  };

  return (
    <div className="max-w-[80rem] mx-auto px-10 pt-9 pb-24">
      <div className="mb-8">
        <h1
          className="text-4xl font-medium tracking-[-0.028em] leading-[1.18] m-0 mb-2"
          style={{ color: "var(--ink)" }}
        >
          {title}
        </h1>
        <div className="text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
          {subtitle}
        </div>
      </div>

      <FilterBar
        actions={actions}
        orgOptions={orgOptions}
        onApply={onApply}
        onExport={() => void exportCsv(filters)}
        isExporting={isExporting}
      />

      {error ? (
        <AppErrorState
          error={error}
          title="Unable to load the audit log"
          description="We couldn't fetch audit entries right now."
          onRetry={() => void refetch()}
          retryLabel="Retry"
        />
      ) : isLoading ? (
        <div
          className="af-card p-10 text-center text-[0.875rem]"
          style={{ color: "var(--ink-3)" }}
        >
          Loading audit log…
        </div>
      ) : (
        <>
          <AuditLogTable logs={logs} showOrg={isAllOrgs} />

          <div className="flex items-center justify-between mt-4">
            <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
              {total} {total === 1 ? "entry" : "entries"}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[0.8125rem]" style={{ color: "var(--ink-4)" }}>
                Page {page} of {totalPages}
              </span>
              <button
                className="af-btn af-btn-ghost text-[0.8125rem]"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Previous
              </button>
              <button
                className="af-btn af-btn-ghost text-[0.8125rem]"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
