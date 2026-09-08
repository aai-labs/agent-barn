"use client";

import { useOrganizationApiBase } from "@/features/organizations/hooks/use-organization-api-base";

import { useSseStream, type SseStreamStatus } from "./use-sse-stream";

export type StreamStatus = SseStreamStatus;

interface UseAgentLogStreamOptions {
  agentId: string;
  enabled: boolean;
  onLine: (line: string) => void;
}

export function useAgentLogStream({
  agentId,
  enabled,
  onLine,
}: UseAgentLogStreamOptions) {
  const orgApiBase = useOrganizationApiBase();

  return useSseStream({
    url: `${orgApiBase}/agents/${agentId}/logs/stream?tail_lines=0`,
    enabled,
    onLine,
  });
}
