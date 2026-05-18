"use client";

import { useState } from "react";
import { Building, Loader2, UserRound } from "lucide-react";
import { useDebouncedValue } from "@tanstack/react-pacer";

import { AppErrorState } from "@/components/app-error-state";
import { ListPageHeader } from "@/components/list-page-header";

import { useInfiniteOrganizations } from "../hooks/use-infinite-organizations";

function LoadingCard() {
  return (
    <div className="af-card px-5 py-[18px] animate-pulse">
      <div className="h-[15px] w-40 rounded-md mb-1.5" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-56 rounded-md mb-4" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-36 rounded-md mb-2" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-44 rounded-md mb-5" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[12px] w-48 rounded-md" style={{ background: "var(--bg-soft)" }} />
    </div>
  );
}

export function OrganizationsGrid() {
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, { wait: 300 });
  const {
    organizations,
    total,
    hasNextPage,
    fetchNextPage,
    error,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteOrganizations({ search: debouncedSearch });

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <ListPageHeader
        title="Organizations"
        description="Super admin view of all organizations."
        count={total}
        noun="organization"
        search={search}
        onSearch={setSearch}
        searchPlaceholder="Search by name, owner, or description"
      />

      {isLoading ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          {Array.from({ length: 6 }).map((_, i) => <LoadingCard key={i} />)}
        </div>
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load organizations"
          description="The organizations list is unavailable right now."
          onRetry={() => { void refetch(); }}
          retryLabel="Retry organizations"
          className="min-h-[240px] p-0"
        />
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          {organizations.map((org) => (
            <div key={org.id} className="af-card af-card-hover px-5 py-[18px]">
              <div className="flex items-center gap-2 mb-1">
                <Building width={14} height={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                <span className="font-semibold text-[14.5px] truncate" style={{ color: "var(--ink)" }}>
                  {org.name}
                </span>
              </div>
              <div className="text-[13px] mb-4 leading-[1.45]" style={{ color: "var(--ink-3)" }}>
                {org.description || "No description"}
              </div>
              <div className="flex items-center gap-1.5 text-[12.5px] mb-1" style={{ color: "var(--ink-3)" }}>
                <UserRound width={12} height={12} style={{ flexShrink: 0 }} />
                {org.ownerName || "No owner name"}
              </div>
              <div className="text-[12.5px] mb-3.5" style={{ color: "var(--ink-3)" }}>
                {org.ownerEmail || "No owner email"}
              </div>
              <div
                className="text-[12px] pt-3"
                style={{ borderTop: "1px solid var(--line)", color: "var(--ink-4)" }}
              >
                Created: {new Date(org.createdAt).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && organizations.length === 0 && (
        <div
          className="flex flex-col items-center justify-center text-center py-16 rounded-2xl"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <div className="font-medium text-[15px] mb-1" style={{ color: "var(--ink)" }}>No organizations found</div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>Try a different search term.</div>
        </div>
      )}

      {hasNextPage && (
        <div className="flex justify-center mt-6">
          <button className="af-btn" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage
              ? <><Loader2 width={14} height={14} className="animate-spin" /> Loading more</>
              : "Load more organizations"}
          </button>
        </div>
      )}
    </div>
  );
}
