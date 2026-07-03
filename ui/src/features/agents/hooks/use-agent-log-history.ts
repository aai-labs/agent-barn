"use client";

import { useCallback, useRef, useState } from "react";

import { api } from "@/shared/api";

import type { AgentLogHistoryRead } from "../schemas";
import { AgentLogHistoryReadSchema } from "../schemas";

const BATCH_SIZE = 50;

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
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const isLoadingRef = useRef(false);
  const offsetRef = useRef(0);

  const reset = useCallback(() => {
    offsetRef.current = 0;
    isLoadingRef.current = false;
    setHasMore(true);
    setIsLoading(false);
  }, []);

  const loadMore = useCallback(async (): Promise<HistoryBatch | null> => {
    if (isLoadingRef.current) return null;
    isLoadingRef.current = true;
    setIsLoading(true);
    try {
      const response = await api.get<AgentLogHistoryRead>(
        `/api/v1/agents/${agentId}/logs/history?offset=${offsetRef.current}&limit=${BATCH_SIZE}`,
        { schema: AgentLogHistoryReadSchema },
      );
      const data = response.data;
      setHasMore(data.hasMore);
      offsetRef.current += data.lines.length;
      return data.lines.length > 0
        ? { lines: data.lines, sessionEndedAt: data.sessionEndedAt ?? null }
        : null;
    } catch {
      setHasMore(false);
      return null;
    } finally {
      isLoadingRef.current = false;
      setIsLoading(false);
    }
  }, [agentId]);

  return { hasMore, isLoading, loadMore, reset };
}
