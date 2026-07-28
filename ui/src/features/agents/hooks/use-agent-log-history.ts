"use client";

import { useCallback, useRef, useState } from "react";

import { api } from "@/shared/api";
import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import type { AgentLogHistoryRead } from "../schemas";
import { AgentLogHistoryReadSchema } from "../schemas";

interface HistoryBatch {
  lines: string[];
  sessionEndedAt: string | null;
}

interface UseAgentLogHistoryReturn {
  hasMore: boolean;
  isLoading: boolean;
  loadMore: () => Promise<HistoryBatch | null>;
  reset: () => void;
}

export function useAgentLogHistory(agentId: string): UseAgentLogHistoryReturn {
  const orgApiBase = useOrganizationApiBase();
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const isLoadingRef = useRef(false);
  const nextSnapshotIdRef = useRef<string | null>(null);
  const exhaustedRef = useRef(false);

  const reset = useCallback(() => {
    nextSnapshotIdRef.current = null;
    exhaustedRef.current = false;
    isLoadingRef.current = false;
    setHasMore(true);
    setIsLoading(false);
  }, []);

  const loadMore = useCallback(async (): Promise<HistoryBatch | null> => {
    if (isLoadingRef.current || exhaustedRef.current) return null;
    isLoadingRef.current = true;
    setIsLoading(true);
    try {
      const snapshotParam = nextSnapshotIdRef.current
        ? `?snapshot_id=${nextSnapshotIdRef.current}`
        : "";
      const response = await api.get<AgentLogHistoryRead>(
        `${orgApiBase}/agents/${agentId}/logs/history${snapshotParam}`,
        { schema: AgentLogHistoryReadSchema },
      );
      const data = response.data;
      nextSnapshotIdRef.current = data.nextSnapshotId ?? null;
      const more = data.hasMore && data.nextSnapshotId != null;
      setHasMore(more);
      if (!more) exhaustedRef.current = true;
      return data.lines.length > 0
        ? { lines: data.lines, sessionEndedAt: data.sessionEndedAt ?? null }
        : null;
    } catch {
      setHasMore(false);
      exhaustedRef.current = true;
      return null;
    } finally {
      isLoadingRef.current = false;
      setIsLoading(false);
    }
  }, [agentId, orgApiBase]);

  return { hasMore, isLoading, loadMore, reset };
}
