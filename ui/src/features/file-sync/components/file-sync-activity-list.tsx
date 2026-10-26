"use client";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/shared/date";

import { useFileSyncActivity } from "../hooks/use-file-sync-activity";
import { fileSyncActivitySentence } from "../utils";

export function FileSyncActivityList({ agentId, providerName }: { agentId: string; providerName: string | null }) {
  const { entries, isLoadingEntries, error, refetch, hasMore, loadMore, isLoadingMore } = useFileSyncActivity(agentId);

  return (
    <section className="af-card p-5" aria-label="File sync activity">
      <h2 className="m-0 mb-3 text-[14px] font-semibold" style={{ color: "var(--ink)" }}>
        What happened
      </h2>
      {error ? (
        <AppErrorState
          error={error}
          title="We couldn't load the sync history"
          description="The list of what File Sync did is unavailable right now."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-[8rem] p-0"
        />
      ) : isLoadingEntries ? (
        <Skeleton className="h-20 w-full" />
      ) : entries.length === 0 ? (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Nothing has happened yet.
        </p>
      ) : (
        <>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {entries.map((entry) => (
              <li key={entry.id} className="flex flex-col gap-0.5">
                <span className="text-[0.86rem]" style={{ color: "var(--ink)" }}>
                  {fileSyncActivitySentence(entry, providerName)}
                </span>
                <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                  {formatDate(entry.occurredAt)}
                </span>
              </li>
            ))}
          </ul>
          {hasMore && (
            <button
              type="button"
              className="af-btn af-btn-ghost af-btn-sm mt-4"
              disabled={isLoadingMore}
              onClick={() => {
                void loadMore();
              }}
            >
              {isLoadingMore ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      )}
    </section>
  );
}
