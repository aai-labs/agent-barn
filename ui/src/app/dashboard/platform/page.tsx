import { Suspense } from "react";
import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformStatsPanel } from "@/features/platform-stats/components/platform-stats-panel";

// The rail lists Platform's pages, so the overview carries only the numbers.
export default function PlatformPage() {
  return (
    <PlatformAdminOnly>
      <div className="af-page">
        <div className="mb-8">
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            Platform
          </h1>
          <p className="mt-2 text-[14.5px]" style={{ color: "var(--ink-3)" }}>
            Product-wide administration outside any active organization.
          </p>
        </div>

        <Suspense fallback={null}>
          <PlatformStatsPanel />
        </Suspense>
      </div>
    </PlatformAdminOnly>
  );
}
