"use client";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Agent } from "@/features/agents/schemas";

import { useFileSyncQuery } from "../hooks/use-file-sync-query";
import { FileSyncStatusCard } from "./file-sync-status-card";

export function FileSyncTab({ agent }: { agent: Agent }) {
  const { fileSync, isLoadingFileSync, error, refetch } = useFileSyncQuery(agent.id);

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load file sync"
        description="The sync status is unavailable right now."
        onRetry={() => {
          void refetch();
        }}
        retryLabel="Retry"
        className="min-h-[12rem] p-0"
      />
    );
  }

  if (isLoadingFileSync || !fileSync) {
    return <Skeleton className="h-32 w-full" />;
  }

  return (
    <div className="flex flex-col gap-4">
      <FileSyncStatusCard agent={agent} fileSync={fileSync} />
    </div>
  );
}
