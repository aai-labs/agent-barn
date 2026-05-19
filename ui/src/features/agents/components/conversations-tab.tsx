"use client";

import { useState } from "react";
import type { Agent } from "../types";
import type { ConversationMessage } from "../types";
import { getConversations } from "../data";
import { AgentAvatar } from "./agent-avatar";

interface ConversationsTabProps {
  agent: Agent;
}

export function ConversationsTab({ agent }: ConversationsTabProps) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
      style={{ border: "1px dashed var(--line-strong)" }}
    >
      <div className="text-3xl mb-3">🚧</div>
      <div className="font-medium text-[15px] mb-1" style={{ color: "var(--ink)" }}>Coming soon</div>
      <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
        Conversation history will appear here soon.
      </div>
    </div>
  );

  const convs = getConversations(agent.id);
  const [selected, setSelected] = useState(0);
  const c = convs[selected];

  return (
    <div className="grid gap-5" style={{ gridTemplateColumns: "320px 1fr" }}>
      <div className="flex flex-col gap-1.5 max-h-[70vh] overflow-y-auto">
        {convs.map((cv, i) => (
          <div
            key={cv.id}
            className="px-3.5 py-3 rounded-xl flex flex-col gap-1 cursor-default"
            style={{ background: i === selected ? "var(--bg-soft)" : "transparent" }}
            onClick={() => setSelected(i)}
            onMouseEnter={(e) => {
              if (i !== selected)
                (e.currentTarget as HTMLElement).style.background = "var(--bg-soft)";
            }}
            onMouseLeave={(e) => {
              if (i !== selected)
                (e.currentTarget as HTMLElement).style.background = "transparent";
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12.5px] font-medium" style={{ color: "var(--ink-2)" }}>
                {cv.channel}
              </span>
              <span className="text-[11.5px]" style={{ color: "var(--ink-4)" }}>
                {cv.t}
              </span>
            </div>
            <div
              className="text-[13px] leading-[1.45] line-clamp-2"
              style={{ color: "var(--ink-3)" }}
            >
              {cv.preview}
            </div>
            <div className="flex items-center justify-between text-[12px]">
              <span style={{ color: "var(--ink-4)" }}>{cv.with}</span>
              {cv.live && (
                <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ok)" }}>
                  <span className="w-1.5 h-1.5 rounded-full af-dot-pulse" style={{ background: "var(--ok)" }} />
                  live
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div
        className="af-card flex flex-col max-h-[70vh] overflow-hidden"
      >
        <div
          className="px-5 py-3.5 flex items-center justify-between flex-shrink-0"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <div>
            <div className="font-mono text-[14.5px] font-semibold" style={{ color: "var(--ink)" }}>
              {c.channel}
            </div>
            <div className="text-[13px] mt-0.5" style={{ color: "var(--ink-4)" }}>
              with {c.with}
            </div>
          </div>
          <button className="af-btn af-btn-sm">Open in Slack ↗</button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-3.5">
          {(c.messages ?? []).map((m, i) => (
            <MessageRow key={i} m={m} agent={agent} />
          ))}
          {c.live && (
            <div className="flex items-center gap-2 pl-8" style={{ color: "var(--ink-3)" }}>
              <AgentAvatar agent={agent} size="xs" />
              <TypingDots />
            </div>
          )}
        </div>

        <div
          className="px-[18px] py-3.5 flex gap-2.5 flex-shrink-0"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <input
            className="af-input flex-1"
            placeholder={`Message ${agent.name}…`}
          />
          <button className="af-btn af-btn-primary">Send</button>
        </div>
      </div>
    </div>
  );
}

function MessageRow({ m, agent }: { m: ConversationMessage; agent: Agent }) {
  if (m.type === "tool") {
    return (
      <div
        className="grid gap-2.5 items-center rounded-lg px-3 py-2.5"
        style={{
          gridTemplateColumns: "22px 1fr",
          background: "var(--bg-soft)",
        }}
      >
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--ink-4)" }}>
          <path d="M14 6a4 4 0 0 1 5.5 5.5l-9 9a3 3 0 0 1-4.2-4.2l9-9z" />
          <path d="M14 6 18 2" />
        </svg>
        <div>
          <div className="font-mono text-[12.5px] font-medium" style={{ color: "var(--ink-2)" }}>
            {m.name}
          </div>
          <div className="font-mono text-[12px]" style={{ color: "var(--ink-3)" }}>
            {m.result}
          </div>
        </div>
      </div>
    );
  }

  const isAgent = m.who === "agent";
  const av = isAgent
    ? agent
    : { initials: (m.who ?? "U").slice(0, 2).toUpperCase(), color: "linear-gradient(135deg, #94a3b8, #475569)", name: m.who ?? "" };

  return (
    <div className="grid gap-2.5 items-start" style={{ gridTemplateColumns: "22px 1fr" }}>
      <AgentAvatar agent={av} size="xs" />
      <div>
        <div className="flex items-baseline gap-2 mb-0.5">
          <b className="text-[12.5px] font-semibold" style={{ color: "var(--ink)" }}>
            {isAgent ? agent.name : m.who}
          </b>
          <span className="text-[11.5px]" style={{ color: "var(--ink-4)" }}>
            {m.t}
          </span>
        </div>
        <div className="text-[14px] leading-[1.5]" style={{ color: "var(--ink)" }}>
          {m.body}
        </div>
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-[5px] h-[5px] rounded-full af-bounce"
          style={{
            background: "var(--ink-4)",
            animationDelay: `${i * 0.15}s`,
          }}
        />
      ))}
    </span>
  );
}
