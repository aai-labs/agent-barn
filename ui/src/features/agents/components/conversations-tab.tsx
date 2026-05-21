"use client";

import { useState } from "react";
import type { Agent, ConversationChannel, ConversationMessage } from "../schemas";
import { useConversations } from "../hooks/use-conversations";

interface ConversationsTabProps {
  agent: Agent;
}

export function ConversationsTab({ agent }: ConversationsTabProps) {
  const { conversations, isLoading, error, refetch } = useConversations(agent.id);
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);

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

  const channels = conversations?.channels ?? [];

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

  const activeChannelId = selectedChannel ?? channels[0]?.channelId;
  const activeChannel = channels.find((c) => c.channelId === activeChannelId) ?? channels[0];

  return (
    <div className="flex rounded-2xl overflow-hidden" style={{ border: "1px solid var(--line-strong)", minHeight: 480 }}>
      <ChannelSidebar
        channels={channels}
        activeChannelId={activeChannelId}
        onSelect={setSelectedChannel}
      />
      <MessagePanel channel={activeChannel} agentName={agent.name} />
    </div>
  );
}

function channelLabel(ch: ConversationChannel): string {
  return `#${ch.channelName ?? ch.channelId.toLowerCase()}`;
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

function MessagePanel({ channel, agentName }: { channel: ConversationChannel | undefined; agentName: string }) {
  if (!channel) return null;

  const allMessages: ConversationMessage[] = channel.sessions
    .flatMap((s) => s.messages)
    .sort((a, b) => new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime());

  const threadSessions = channel.sessions.filter((s) => s.threadId !== null);
  const threadMessageIds = new Set(threadSessions.flatMap((s) => s.messages.map((m) => m.id)));
  const channelMessages = allMessages.filter((m) => !threadMessageIds.has(m.id));

  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      <div
        className="px-5 py-3 text-[0.75rem] uppercase tracking-[0.08em] font-semibold"
        style={{ borderBottom: "1px solid var(--line-strong)", color: "var(--ink-3)" }}
      >
        {channelLabel(channel)}
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-1">
        {channelMessages.map((msg) => (
          <MessageRow key={msg.id} message={msg} agentName={agentName} />
        ))}
        {threadSessions.map((session) => (
          <ThreadBlock key={session.sessionKey} session={session} agentName={agentName} />
        ))}
      </div>
    </div>
  );
}

function MessageRow({ message, agentName, indent = false }: { message: ConversationMessage; agentName: string; indent?: boolean }) {
  const isIn = message.direction === "INBOUND";
  const time = new Date(message.occurredAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const senderLabel = isIn ? (message.senderName || message.senderId) : agentName;

  return (
    <div
      className={`flex items-start gap-3 py-1.5 px-2 rounded-lg ${indent ? "ml-6" : ""}`}
      style={{ background: "transparent" }}
    >
      <span className="text-[0.7rem] mt-0.5 w-[3.5rem] flex-shrink-0 tabular-nums" style={{ color: "var(--ink-4, var(--ink-3))" }}>
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
      <span className="text-[0.875rem] leading-relaxed" style={{ color: "var(--ink)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {message.content}
      </span>
    </div>
  );
}

function ThreadBlock({ session, agentName }: { session: { sessionKey: string; threadId: string | null; messages: ConversationMessage[] }; agentName: string }) {
  const [expanded, setExpanded] = useState(true);
  const sorted = [...session.messages].sort(
    (a, b) => new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime()
  );

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
          Thread · {sorted.length} {sorted.length === 1 ? "message" : "messages"}
        </span>
      </button>
      {expanded && (
        <div className="px-2 py-1 flex flex-col gap-0.5" style={{ background: "var(--bg)" }}>
          {sorted.map((msg) => (
            <MessageRow key={msg.id} message={msg} agentName={agentName} indent />
          ))}
        </div>
      )}
    </div>
  );
}

function ConversationsSkeleton() {
  return (
    <div className="flex rounded-2xl overflow-hidden animate-pulse" style={{ border: "1px solid var(--line-strong)", minHeight: 480 }}>
      <div className="w-44 flex-shrink-0" style={{ background: "var(--bg-soft)", borderRight: "1px solid var(--line-strong)" }} />
      <div className="flex-1 px-5 py-4 flex flex-col gap-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex gap-3 items-start">
            <div className="h-4 w-10 rounded" style={{ background: "var(--bg-soft)" }} />
            <div className="h-4 w-8 rounded" style={{ background: "var(--bg-soft)" }} />
            <div className="h-4 rounded flex-1" style={{ background: "var(--bg-soft)", maxWidth: `${40 + i * 10}%` }} />
          </div>
        ))}
      </div>
    </div>
  );
}
