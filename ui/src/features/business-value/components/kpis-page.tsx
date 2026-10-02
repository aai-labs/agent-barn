"use client";

import { useRequireOrgManager } from "@/features/organizations/hooks/use-require-org-manager";

export function KpisPage() {
  const canManage = useRequireOrgManager();

  if (!canManage) return null;

  return <KpiDashboard />;
}

function KpiDashboard() {
  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="mb-7">
        <h1
          className="text-[28px] font-semibold tracking-tight m-0 mb-1"
          style={{ color: "var(--ink)" }}
        >
          KPIs
        </h1>
        <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
          The value your agents produce against what they cost, and how reliably they work.
        </p>
      </div>
    </div>
  );
}
