import { Suspense } from "react";
import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformStatsPanel } from "@/features/platform-stats/components/platform-stats-panel";

// The rail lists Platform's pages, so the overview carries only the numbers, headed by
// the stats panel.
export default function PlatformPage() {
  return (
    <PlatformAdminOnly>
      <div className="af-page">
        <Suspense fallback={null}>
          <PlatformStatsPanel />
        </Suspense>
      </div>
    </PlatformAdminOnly>
  );
}
