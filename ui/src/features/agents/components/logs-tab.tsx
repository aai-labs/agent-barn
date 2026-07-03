"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";

import type { Agent } from "../schemas";
import { useAgentLogs } from "../hooks/use-agent-logs";
import { useAgentLogStream } from "../hooks/use-agent-log-stream";
import { useAgentLogHistory } from "../hooks/use-agent-log-history";

interface LogsTabProps {
  agent: Agent;
}

const MAX_BUFFER_LINES = 10_000;

export function LogsTab({ agent }: LogsTabProps) {
  const isRunning = agent.status === "RUNNING";
  const { logs, isLoading, error, refetch } = useAgentLogs(agent.id);
  const [lines, setLines] = useState<string[]>([]);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const prevStatusRef = useRef(agent.status);
  const prevScrollHeightRef = useRef(0);
  const isRunningRef = useRef(isRunning);
  isRunningRef.current = isRunning;

  const { hasMore, isLoading: isLoadingHistory, loadMore, reset } = useAgentLogHistory(agent.id);

  useEffect(() => {
    if (logs?.lines && logs.source === "live") {
      setLines(logs.lines);
    }
  }, [logs]);

  useEffect(() => {
    if (prevStatusRef.current !== agent.status) {
      prevStatusRef.current = agent.status;
      reset();
      setLines([]);
      void refetch();
    }
  }, [agent.status, refetch, reset]);

  const handleNewLine = useCallback((line: string) => {
    setLines((prev) => {
      const next = [...prev, line];
      return next.length > MAX_BUFFER_LINES
        ? next.slice(next.length - MAX_BUFFER_LINES)
        : next;
    });
  }, []);

  const { status: streamStatus } = useAgentLogStream({
    agentId: agent.id,
    enabled: isRunning,
    onLine: handleNewLine,
  });

  const handleLoadMore = useCallback(async () => {
    if (!scrollRef.current) return;
    prevScrollHeightRef.current = scrollRef.current.scrollHeight;

    const result = await loadMore();
    if (!result || !isRunningRef.current) return;

    setLines((prev) => {
      const separator = result.sessionEndedAt
        ? ["", `===  Session ended ${new Date(result.sessionEndedAt).toLocaleString()}   ===`, ""]
        : [];
      return [...result.lines, ...separator, ...prev];
    });
  }, [loadMore]);

  useLayoutEffect(() => {
    if (prevScrollHeightRef.current > 0 && scrollRef.current) {
      const delta = scrollRef.current.scrollHeight - prevScrollHeightRef.current;
      if (delta > 0) {
        scrollRef.current.scrollTop += delta;
      }
      prevScrollHeightRef.current = 0;
    }
  }, [lines]);

  useLayoutEffect(() => {
    if (isAtBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, isAtBottom]);

  useEffect(() => {
    const container = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!container || !sentinel) return;

    const showHistory = isRunning && logs?.source === "live" && logs?.hasSnapshots && hasMore && !isLoadingHistory;
    if (!showHistory) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          void handleLoadMore();
        }
      },
      { root: container, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [isRunning, logs?.source, logs?.hasSnapshots, hasMore, isLoadingHistory, handleLoadMore]);

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const threshold = 50;
    setIsAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < threshold);
  }

  function jumpToLatest() {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsAtBottom(true);
    }
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load logs"
        description="The log data is unavailable right now."
        onRetry={() => { void refetch(); }}
        retryLabel="Retry"
        className="min-h-[15rem] p-0"
      />
    );
  }

  return (
    <div className="relative">
      <div
        className="flex items-center justify-between px-4 py-2.5 rounded-t-xl"
        style={{ background: "var(--bg-soft)", borderBottom: "1px solid var(--line)" }}
      >
        <span className="text-[0.8125rem] font-medium" style={{ color: "var(--ink-2)" }}>
          {isRunning ? "Live logs" : "Logs"}
        </span>
        {isRunning && streamStatus === "streaming" && (
          <span className="flex items-center gap-1.5 text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: "var(--ok)" }}
            />
            Streaming
          </span>
        )}
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-y-auto font-mono text-[0.8125rem] leading-[1.6] px-4 py-3 rounded-b-xl"
        style={{
          background: "var(--bg-deep, #0d1117)",
          color: "var(--ink-on-deep, #c9d1d9)",
          height: "32rem",
          border: "1px solid var(--line)",
          borderTop: "none",
        }}
      >
        <div ref={sentinelRef} className="h-px" />

        {isLoadingHistory && (
          <div className="text-center py-2 text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
            Loading earlier logs...
          </div>
        )}

        {isLoading && (
          <div className="text-center py-12" style={{ color: "var(--ink-4)" }}>
            Loading logs...
          </div>
        )}
        {!isLoading && lines.length === 0 && (
          <div className="text-center py-12" style={{ color: "var(--ink-4)" }}>
            No logs available
          </div>
        )}
        {lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all min-h-[1.6em]">
            {line || " "}
          </div>
        ))}
      </div>

      {!isAtBottom && lines.length > 0 && (
        <button
          onClick={jumpToLatest}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-lg text-[0.75rem] font-medium shadow-md cursor-pointer"
          style={{
            background: "var(--accent)",
            color: "var(--ink-on-accent, #040404)",
          }}
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
