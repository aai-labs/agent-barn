"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AppErrorState } from "@/components/app-error-state";

import type { Agent } from "../schemas";
import { useAgentLogs } from "../hooks/use-agent-logs";
import { useAgentLogStream } from "../hooks/use-agent-log-stream";

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
  const prevStatusRef = useRef(agent.status);

  useEffect(() => {
    if (logs?.lines) {
      setLines(logs.lines);
    }
  }, [logs]);

  useEffect(() => {
    if (prevStatusRef.current !== agent.status) {
      prevStatusRef.current = agent.status;
      void refetch();
    }
  }, [agent.status, refetch]);

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

  useLayoutEffect(() => {
    if (isAtBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines.length, isAtBottom]);

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
          {logs?.source === "snapshot" && logs.sessionEndedAt
            ? `Session ended ${new Date(logs.sessionEndedAt).toLocaleString()}`
            : "Live logs"}
        </span>
        {isRunning && (
          <span className="flex items-center gap-1.5 text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background:
                  streamStatus === "streaming"
                    ? "var(--ok)"
                    : streamStatus === "connecting"
                      ? "var(--warn, #f59e0b)"
                      : "var(--ink-4)",
              }}
            />
            {streamStatus === "streaming"
              ? "Streaming"
              : streamStatus === "connecting"
                ? "Connecting..."
                : "Disconnected"}
          </span>
        )}
      </div>

      {isRunning && logs?.hasSnapshots && (
        <div
          className="px-4 py-2 text-[0.75rem]"
          style={{
            background: "color-mix(in srgb, var(--accent) 8%, transparent)",
            borderBottom: "1px solid var(--line)",
            color: "var(--ink-3)",
          }}
        >
          Previous session logs available via snapshots
        </div>
      )}

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
          className="absolute bottom-4 right-4 px-3 py-1.5 rounded-lg text-[0.75rem] font-medium shadow-md cursor-pointer"
          style={{
            background: "var(--accent)",
            color: "var(--ink-on-accent, #fff)",
          }}
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
