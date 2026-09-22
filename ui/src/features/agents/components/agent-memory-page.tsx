"use client";

import { useState } from "react";

import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { useMemoryGroupMutations } from "@/features/memory-groups/hooks/use-memory-group-mutations";

import { type MemoryScope, useAgentMemory, useAgentMemoryFacets, useAgentMemorySearch } from "../hooks/use-agent-memory";
import { MemoryView } from "./memory-view";

const PAGE_SIZE = 50;

/** The Memory tab on an Agent's detail page: the agent's pool memory, with the
 *  "Whole group / This agent" scope and per-item edit/forget/share. Thin wrapper
 *  over the shared MemoryView, which the per-group page also uses. */
export function AgentMemoryPage({
  agentId,
  agentName,
  sourceGroupId,
}: {
  agentId: string;
  agentName: string;
  // The agent's memory group, or null when it is in none. Sharing an item is a
  // pool-to-pool operation, so it is only offered when the agent has a pool.
  sourceGroupId: string | null;
}) {
  const [page, setPage] = useState(1);
  const [peer, setPeer] = useState<string | null>(null);
  const [scope, setScope] = useState<MemoryScope>("pool");
  const [search, setSearch] = useState("");

  const { memory, isLoading, error, forget, correct } = useAgentMemory(agentId, page, PAGE_SIZE, peer, scope);
  const facets = useAgentMemoryFacets(agentId, scope);
  const searchQuery = useAgentMemorySearch(agentId, search);
  const isSearching = search.trim().length > 2;

  const { canManage } = useActiveOrgRole();
  const { shareItem } = useMemoryGroupMutations();

  return (
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
      searchPlaceholder="Search this agent's memory…"
      forget={(memoryId) => forget.mutateAsync(memoryId)}
      correct={(memoryId, content) => correct.mutateAsync({ memoryId, content })}
      isForgetting={forget.isPending}
      isCorrecting={correct.isPending}
      selfLabel={agentName}
      scope={scope}
      onScopeChange={(next) => {
        setScope(next);
        // Switching scope changes which facets exist, so reset the peer + page.
        setPeer(null);
        setPage(1);
      }}
      share={canManage && sourceGroupId ? { sourceGroupId, shareItem } : undefined}
      errorText="Could not load this agent's memory. Try again in a moment."
      emptyTitle="Nothing learned yet"
      emptyBody={`Memories appear here after ${agentName} has held a conversation. You can then correct, forget, or share any of them.`}
    />
  );
}
