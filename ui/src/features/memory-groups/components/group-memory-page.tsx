"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { MemoryView } from "@/features/agents/components/memory-view";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { useMemoryGroups } from "../hooks/use-memory-groups";
import { useMemoryGroupMutations } from "../hooks/use-memory-group-mutations";
import { useGroupMemory, useGroupMemoryFacets, useGroupMemorySearch } from "../hooks/use-group-memory";

const PAGE_SIZE = 50;

/** A group's shared memory, managed from the group rather than an individual agent.
 *  Thin wrapper over the shared MemoryView with the group-scoped hooks. */
export function GroupMemoryPage({ groupId }: { groupId: string }) {
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const { canManage } = useActiveOrgRole();
  const { groups } = useMemoryGroups();
  const groupName = groups.find((g) => g.id === groupId)?.name ?? "Group";

  const [page, setPage] = useState(1);
  const [peer, setPeer] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { memory, isLoading, error, forget, correct } = useGroupMemory(groupId, page, PAGE_SIZE, peer);
  const facets = useGroupMemoryFacets(groupId);
  const searchQuery = useGroupMemorySearch(groupId, search);
  const isSearching = search.trim().length > 2;
  const { shareItem } = useMemoryGroupMutations();

  return (
    <div style={{ background: "var(--bg)" }}>
      <main className="af-page">
        <Link
          href={`/dashboard/${orgId}/settings?tab=memory-groups`}
          className="mb-4 inline-flex items-center gap-1.5 text-[0.8125rem]"
          style={{ color: "var(--ink-3)" }}
        >
          <ArrowLeft size={15} aria-hidden /> Memory Groups
        </Link>
        <h1 className="m-0 text-[2rem] font-semibold tracking-[-0.025em]" style={{ color: "var(--ink)" }}>
          {groupName}
        </h1>
        <p className="mt-1 mb-6 text-[0.9rem]" style={{ color: "var(--ink-3)" }}>
          Shared memory for this group — every agent in it draws on and contributes to it.
        </p>

        <MemoryView
          items={isSearching ? (searchQuery.data ?? []) : (memory?.items ?? [])}
          total={memory?.total ?? 0}
          pageSize={PAGE_SIZE}
          facets={facets}
          isLoading={isLoading}
          error={error}
          page={page}
          onPageChange={setPage}
          peer={peer}
          onSelectPeer={(next) => {
            setPeer(next);
            setPage(1);
          }}
          search={search}
          onSearchChange={setSearch}
          isSearching={isSearching}
          searchPending={searchQuery.isPending}
          searchPlaceholder="Search this group's memory…"
          forget={(memoryId) => forget.mutateAsync(memoryId)}
          correct={(memoryId, content) => correct.mutateAsync({ memoryId, content })}
          isForgetting={forget.isPending}
          isCorrecting={correct.isPending}
          selfLabel={null}
          share={canManage ? { sourceGroupId: groupId, shareItem } : undefined}
          errorText="Could not load this group's memory. Try again in a moment."
          emptyTitle="No memory in this group yet"
          emptyBody="Memory appears here after an agent in this group has held a conversation. You can then correct, forget, or share any of it."
        />
      </main>
    </div>
  );
}
