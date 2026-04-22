"use client";

import { Skeleton } from "@/components/ui/skeleton";

export function UserDashboard() {
  return (
    <div className="space-y-4">
      <div className="grid auto-rows-min gap-4 md:grid-cols-3">
        <Skeleton className="aspect-video rounded-xl" />
        <Skeleton className="aspect-video rounded-xl" />
        <Skeleton className="aspect-video rounded-xl" />
      </div>
      <Skeleton className="min-h-screen flex-1 rounded-xl md:min-h-min" />
    </div>
  );
}
