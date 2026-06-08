"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryState, parseAsString } from "nuqs";

import type { Agent, ConversationChannel, ConversationMessage, ConversationThread } from "../schemas";
import {
  useChannelMessages,
  useConversationChannels,
} from "../hooks/use-conversations";

interface ConversationsTabProps {
  agent: Agent;
}

function channelLabel(ch: ConversationChannel): string {
  if (ch.conversationType === "DM") {
    return ch.channelName ?? ch.channelId;
  }
  return `#${ch.channelName ?? ch.channelId.toLowerCase()}`;
}

export function ConversationsTab({ agent }: ConversationsTabProps) {
  const { channels, isLoading, error, refetch } = useConversationChannels(agent.id);
  const [selectedChannel, setSelectedChannel] = useQueryState(
    "channel",
    parseAsString.withOptions({ history: "replace", scroll: false }),
  );

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

  const channelConvos = channels.filter((c) => c.conversationType === "CHANNEL");
  const dmConvos = channels.filter((c) => c.conversationType === "DM");

  return (
    <div
      className="flex rounded-2xl overflow-hidden"
      style={{ border: "1px solid var(--line-strong)", height: "min(760px, 80vh)" }}
    >
      <ConversationSidebar
        channelConvos={channelConvos}
        dmConvos={dmConvos}
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

function ConversationSidebar({
  channelConvos,
  dmConvos,
  activeChannelId,
  onSelect,
}: {
  channelConvos: ConversationChannel[];
  dmConvos: ConversationChannel[];
  activeChannelId: string;
  onSelect: (id: string) => void;
}) {
  function SidebarItem({ ch }: { ch: ConversationChannel }) {
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
  }

  return (
    <div
      className="w-44 flex-shrink-0 flex flex-col overflow-y-auto"
      style={{ borderRight: "1px solid var(--line-strong)", background: "var(--bg-soft)" }}
    >
      {channelConvos.length > 0 && (
        <>
          <div
            className="px-4 py-3 text-[0.75rem] uppercase tracking-[0.08em] font-semibold"
            style={{ color: "var(--ink-3)" }}
          >
            Channels
          </div>
          {channelConvos.map((ch) => <SidebarItem key={ch.channelId} ch={ch} />)}
        </>
      )}
      {dmConvos.length > 0 && (
        <>
          <div
            className="px-4 py-3 text-[0.75rem] uppercase tracking-[0.08em] font-semibold"
            style={{ color: "var(--ink-3)", marginTop: channelConvos.length > 0 ? "0.25rem" : 0 }}
          >
            Direct Messages
          </div>
          {dmConvos.map((ch) => <SidebarItem key={ch.channelId} ch={ch} />)}
        </>
      )}
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

  const allThreads: ConversationThread[] = useMemo(() => {
    if (!data) return [];
    const oldestFirst = [...data.pages].reverse();
    return oldestFirst.flatMap((p) => p.threads);
  }, [data]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
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
    if (!initialScrolledRef.current && allThreads.length > 0) {
      el.scrollTop = el.scrollHeight;
      initialScrolledRef.current = true;
    }
  }, [allThreads.length]);

  function loadEarlier() {
    const el = scrollRef.current;
    if (el) preservedScrollHeightRef.current = el.scrollHeight;
    fetchNextPage();
  }

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
        {hasNextPage && (
          <div className="flex justify-center py-2">
            <button
              onClick={loadEarlier}
              disabled={isFetchingNextPage}
              className="text-[0.75rem] px-4 py-1.5 rounded-lg transition-colors"
              style={{
                color: "var(--ink)",
                border: "1px solid var(--line-strong)",
                background: "var(--bg-soft)",
                opacity: isFetchingNextPage ? 0.6 : 1,
                cursor: isFetchingNextPage ? "default" : "pointer",
              }}
            >
              {isFetchingNextPage ? "Fetching…" : "Load earlier conversations"}
            </button>
          </div>
        )}
        {!hasNextPage && allThreads.length > 0 && (
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
        {!isLoading && allThreads.length === 0 && (
          <div className="text-center text-[0.844rem] py-12" style={{ color: "var(--ink-3)" }}>
            No messages in this range.
          </div>
        )}
        {allThreads.map((thread) => (
          <div key={thread.root.id}>
            <MessageRow message={thread.root} agentName={agentName} />
            {thread.replies.length > 0 && (
              <ThreadBlock messages={thread.replies} agentName={agentName} />
            )}
          </div>
        ))}
      </div>
    </div>
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
      style={{ border: "1px solid var(--line-strong)", minHeight: 620 }}
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
