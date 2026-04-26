"use client";

import { RouteErrorState } from "@/components/route-error-state";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <RouteErrorState
      error={error}
      reset={reset}
      title="We couldn't load this dashboard page"
      description="A page-level request failed before the dashboard content could load."
      className="min-h-[calc(100svh-4rem)]"
    />
  );
}
