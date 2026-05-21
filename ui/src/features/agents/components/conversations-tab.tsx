"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { Agent, ConversationChannel, ConversationMessage } from "../schemas";
import {
  useChannelMessages,
  useConversationChannels,
} from "../hooks/use-conversations";

interface ConversationsTabProps {
  agent: Agent;
}

function channelLabel(ch: ConversationChannel): string {
  return `#${ch.channelName ?? ch.channelId.toLowerCase()}`;
}

function readChannelFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("channel");
}

function writeChannelToUrl(channelId: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (channelId) url.searchParams.set("channel", channelId);
  else url.searchParams.delete("channel");
  window.history.replaceState({}, "", url.toString());
}

export function ConversationsTab({ agent }: ConversationsTabProps) {
  const { channels, isLoading, error, refetch } = useConversationChannels(agent.id);
  const [selectedChannel, setSelectedChannel] = useState<string | null>(
    () => readChannelFromUrl(),
  );

  useEffect(() => {
    if (!selectedChannel && channels.length > 0) {
      setSelectedChannel(channels[0].channelId);
    }
  }, [channels, selectedChannel]);

  useEffect(() => {
    writeChannelToUrl(selectedChannel);
  }, [selectedChannel]);

  if (isLoading) return <ConversationsSkeleton />;

  if (error) {
    return (
      <div
        className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
        style={{ border: "1px dashed var(--line-strong)" }}
      >
        <div className="font-medium text-[0.9375rem] mb-2" style={{ color: "var(--ink)" }}>
          Failed to load conversations
        </div>
        <button
          onClick={() => refetch()}
          className="text-[0.844rem] px-4 py-1.5 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--accent, #4f46e5)", border: "1px solid var(--line-strong)" }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (channels.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
        style={{ border: "1px dashed var(--line-strong)" }}
      >
        <div className="text-3xl mb-3">💬</div>
        <div className="font-medium text-[0.9375rem] mb-1" style={{ color: "var(--ink)" }}>
          No conversations yet
        </div>
        <div className="text-[0.844rem]" style={{ color: "var(--ink-3)" }}>
          Messages will appear here once the agent starts receiving Slack messages.
        </div>
      </div>
    );
  }

  const activeChannel =
    channels.find((c) => c.channelId === selectedChannel) ?? channels[0];

  return (
    <div
      className="flex rounded-2xl overflow-hidden"
      style={{ border: "1px solid var(--line-strong)", minHeight: 480 }}
    >
      <ChannelSidebar
        channels={channels}
        activeChannelId={activeChannel.channelId}
        onSelect={setSelectedChannel}
      />
      <MessagePanel
        key={activeChannel.channelId}
        agentId={agent.id}
        agentName={agent.name}
        channel={activeChannel}
      />
    </div>
  );
}

function ChannelSidebar({
  channels,
  activeChannelId,
  onSelect,
}: {
  channels: ConversationChannel[];
  activeChannelId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      className="w-44 flex-shrink-0 flex flex-col overflow-y-auto"
      style={{ borderRight: "1px solid var(--line-strong)", background: "var(--bg-soft)" }}
    >
      <div
        className="px-4 py-3 text-[0.75rem] uppercase tracking-[0.08em] font-semibold"
        style={{ color: "var(--ink-3)" }}
      >
        Channels
      </div>
      {channels.map((ch) => {
        const active = ch.channelId === activeChannelId;
        return (
          <button
            key={ch.channelId}
            onClick={() => onSelect(ch.channelId)}
            className="w-full text-left px-4 py-2 text-[0.844rem] font-medium transition-colors"
            style={{
              color: active ? "var(--ink)" : "var(--ink-3)",
              background: active ? "var(--bg)" : "transparent",
              borderLeft: active ? "2px solid var(--accent, #4f46e5)" : "2px solid transparent",
            }}
          >
            {channelLabel(ch)}
          </button>
        );
      })}
    </div>
  );
}

function toIso(localDatetimeValue: string): string {
  if (!localDatetimeValue) return "";
  const d = new Date(localDatetimeValue);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString();
}

function MessagePanel({
  agentId,
  agentName,
  channel,
}: {
  agentId: string;
  agentName: string;
  channel: ConversationChannel;
}) {
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const filters = useMemo(
    () => ({ fromDate: toIso(fromDate), toDate: toIso(toDate) }),
    [fromDate, toDate],
  );

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
  } = useChannelMessages(agentId, channel.channelId, filters);

  const allMessages: ConversationMessage[] = useMemo(() => {
    if (!data) return [];
    const oldestFirst = [...data.pages].reverse();
    return oldestFirst.flatMap((p) => p.messages);
  }, [data]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const topSentinelRef = useRef<HTMLDivElement | null>(null);
  const initialScrolledRef = useRef(false);
  const preservedScrollHeightRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (preservedScrollHeightRef.current !== null) {
      el.scrollTop = el.scrollHeight - preservedScrollHeightRef.current;
      preservedScrollHeightRef.current = null;
      return;
    }
    if (!initialScrolledRef.current && allMessages.length > 0) {
      el.scrollTop = el.scrollHeight;
      initialScrolledRef.current = true;
    }
  }, [allMessages.length]);

  const requestOlder = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (!hasNextPage || isFetchingNextPage) return;
    preservedScrollHeightRef.current = el.scrollHeight;
    fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  useEffect(() => {
    const sentinel = topSentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) requestOlder();
        }
      },
      { root, threshold: 0, rootMargin: "100px 0px 0px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [requestOlder]);

  const threadIds = useMemo(() => {
    const ids = new Set<string>();
    for (const m of allMessages) if (m.threadId !== null) ids.add(m.id);
    return ids;
  }, [allMessages]);

  const channelMessages = allMessages.filter((m) => !threadIds.has(m.id));
  const threadsByRoot = useMemo(() => {
    const map = new Map<string, ConversationMessage[]>();
    for (const m of allMessages) {
      if (m.threadId !== null) {
        const arr = map.get(m.threadId) ?? [];
        arr.push(m);
        map.set(m.threadId, arr);
      }
    }
    return map;
  }, [allMessages]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      <div
        className="px-5 py-3 flex items-center gap-3 flex-wrap"
        style={{ borderBottom: "1px solid var(--line-strong)" }}
      >
        <div
          className="text-[0.75rem] uppercase tracking-[0.08em] font-semibold"
          style={{ color: "var(--ink-3)" }}
        >
          {channelLabel(channel)}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <label className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
            From
          </label>
          <input
            type="datetime-local"
            className="af-input"
            style={{ width: "13rem" }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <label className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
            To
          </label>
          <input
            type="datetime-local"
            className="af-input"
            style={{ width: "13rem" }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </div>
      </div>
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-1"
        style={{ minHeight: 0 }}
      >
        <div ref={topSentinelRef} />
        {isFetchingNextPage && (
          <div
            className="text-center text-[0.75rem] py-2"
            style={{ color: "var(--ink-3)" }}
          >
            Loading earlier conversations…
          </div>
        )}
        {!hasNextPage && allMessages.length > 0 && (
          <div
            className="text-center text-[0.7rem] py-2"
            style={{ color: "var(--ink-3)" }}
          >
            Beginning of conversation
          </div>
        )}
        {error && (
          <div className="text-center text-[0.844rem] py-4" style={{ color: "var(--ink-3)" }}>
            Failed to load messages
          </div>
        )}
        {isLoading && !data && (
          <div className="flex flex-col gap-2 py-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-4 rounded animate-pulse" style={{ background: "var(--bg-soft)" }} />
            ))}
          </div>
        )}
        {!isLoading && allMessages.length === 0 && (
          <div className="text-center text-[0.844rem] py-12" style={{ color: "var(--ink-3)" }}>
            No messages in this range.
          </div>
        )}
        {channelMessages.map((msg) => {
          const matchingThread = findThreadForChannelMessage(
            msg,
            threadsByRoot,
          );
          return (
            <div key={msg.id}>
              <MessageRow message={msg} agentName={agentName} />
              {matchingThread && matchingThread.length > 0 && (
                <ThreadBlock messages={matchingThread} agentName={agentName} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function findThreadForChannelMessage(
  channelMsg: ConversationMessage,
  threadsByRoot: Map<string, ConversationMessage[]>,
): ConversationMessage[] | null {
  const channelTs = new Date(channelMsg.occurredAt).getTime() / 1000;
  let best: { id: string; delta: number } | null = null;
  for (const threadId of threadsByRoot.keys()) {
    const threadTs = parseFloat(threadId);
    if (Number.isNaN(threadTs)) continue;
    const delta = Math.abs(threadTs - channelTs);
    if (delta <= 5 && (best === null || delta < best.delta)) {
      best = { id: threadId, delta };
    }
  }
  if (!best) return null;
  return [...(threadsByRoot.get(best.id) ?? [])].sort(
    (a, b) => new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime(),
  );
}

function MessageRow({
  message,
  agentName,
  indent = false,
}: {
  message: ConversationMessage;
  agentName: string;
  indent?: boolean;
}) {
  const isIn = message.direction === "INBOUND";
  const time = new Date(message.occurredAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const senderLabel = isIn ? message.senderName || message.senderId : agentName;

  return (
    <div
      className={`flex items-start gap-3 py-1.5 px-2 rounded-lg ${indent ? "ml-6" : ""}`}
      style={{ background: "transparent" }}
    >
      <span
        className="text-[0.7rem] mt-0.5 w-[3.5rem] flex-shrink-0 tabular-nums"
        style={{ color: "var(--ink-4, var(--ink-3))" }}
      >
        {time}
      </span>
      {senderLabel && (
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] font-semibold tracking-wide flex-shrink-0 mt-0.5"
          style={{
            background: isIn ? "rgba(167,139,250,0.35)" : "rgba(74,222,128,0.35)",
            color: "#000",
          }}
        >
          {senderLabel}
        </span>
      )}
      <span
        className="text-[0.875rem] leading-relaxed"
        style={{ color: "var(--ink)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
      >
        {message.content}
      </span>
    </div>
  );
}

function ThreadBlock({
  messages,
  agentName,
}: {
  messages: ConversationMessage[];
  agentName: string;
}) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div
      className="ml-4 mt-1 mb-1 rounded-lg overflow-hidden"
      style={{ border: "1px solid var(--line-strong)" }}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        style={{ background: "var(--bg-soft)" }}
      >
        <span className="text-[0.7rem]" style={{ color: "var(--ink-3)" }}>
          {expanded ? "▾" : "▸"}
        </span>
        <span className="text-[0.75rem] font-medium" style={{ color: "var(--ink-3)" }}>
          Thread · {messages.length} {messages.length === 1 ? "message" : "messages"}
        </span>
      </button>
      {expanded && (
        <div className="px-2 py-1 flex flex-col gap-0.5" style={{ background: "var(--bg)" }}>
          {messages.map((msg) => (
            <MessageRow key={msg.id} message={msg} agentName={agentName} indent />
          ))}
        </div>
      )}
    </div>
  );
}

function ConversationsSkeleton() {
  return (
    <div
      className="flex rounded-2xl overflow-hidden animate-pulse"
      style={{ border: "1px solid var(--line-strong)", minHeight: 480 }}
    >
      <div
        className="w-44 flex-shrink-0"
        style={{ background: "var(--bg-soft)", borderRight: "1px solid var(--line-strong)" }}
      />
      <div className="flex-1 px-5 py-4 flex flex-col gap-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex gap-3 items-start">
            <div className="h-4 w-10 rounded" style={{ background: "var(--bg-soft)" }} />
            <div className="h-4 w-8 rounded" style={{ background: "var(--bg-soft)" }} />
            <div
              className="h-4 rounded flex-1"
              style={{ background: "var(--bg-soft)", maxWidth: `${40 + i * 10}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
