"use client";

import { useEffect, useMemo, useState } from "react";
import { Maximize2, Minimize2, Plus } from "lucide-react";
import { useQueryState, parseAsString } from "nuqs";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { cn } from "@/lib/utils";

import type { Agent, WebChatMessage } from "../schemas";
import { MAIN_THREAD_ID, useWebChat } from "../hooks/use-web-chat";
import { useWebChatThreads } from "../hooks/use-web-chat-threads";
import { AgentAvatar } from "./agent-avatar";

interface ChatTabProps {
  agent: Agent;
}

function convertMessage(message: WebChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.direction === "OUTBOUND" ? "assistant" : "user",
    content: [{ type: "text", text: message.content }],
    createdAt: new Date(message.occurredAt),
  };
}

function threadLabel(threadId: string) {
  return threadId === MAIN_THREAD_ID ? "Main chat" : `Chat ${threadId.slice(0, 8)}`;
}

export function ChatTab({ agent }: ChatTabProps) {
  const [threadId, setThreadId] = useQueryState(
    "thread",
    parseAsString.withDefault(MAIN_THREAD_ID).withOptions({ history: "replace" }),
  );

  const { messages, sendMessage, isSending, streamStatus } = useWebChat(
    agent.id,
    threadId,
    true,
  );
  const { threads, refetch: refetchThreads } = useWebChatThreads(agent.id, true);

  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    if (!isMaximized) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setIsMaximized(false);
    }
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isMaximized]);

  function startNewChat() {
    void setThreadId(crypto.randomUUID());
  }

  const runtime = useExternalStoreRuntime<WebChatMessage>({
    messages,
    isRunning: isSending,
    convertMessage,
    onNew: async (message) => {
      const part = message.content.find((p) => p.type === "text");
      if (!part || part.type !== "text") return;
      await sendMessage(part.text);
      void refetchThreads();
    },
  });

  const isLive = streamStatus === "streaming";

  // `threads` is already most-recent-first. A brand-new thread (no messages
  // sent yet) isn't in that list, so it goes first — it's the newest one, by
  // definition more recent than anything with a message already in it. Main
  // chat still always appears (even with zero messages, for discoverability
  // of the default thread), but only pinned to the end if nothing else put
  // it earlier.
  const sidebarThreads = useMemo(() => {
    const known = new Map(threads.map((t) => [t.threadId, t]));
    const ids = [...threads.map((t) => t.threadId)];
    if (!known.has(threadId)) ids.unshift(threadId);
    if (!known.has(MAIN_THREAD_ID) && threadId !== MAIN_THREAD_ID) ids.push(MAIN_THREAD_ID);
    return ids.map((id) => ({ threadId: id, lastContent: known.get(id)?.lastContent }));
  }, [threads, threadId]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div
        className={cn(
          "flex overflow-hidden",
          isMaximized ? "fixed inset-4 z-50 rounded-2xl shadow-2xl" : "rounded-2xl",
        )}
        style={{
          border: "1px solid var(--line)",
          height: isMaximized ? undefined : "34rem",
          background: "var(--bg)",
        }}
      >
        <div
          className="flex w-56 flex-shrink-0 flex-col"
          style={{ borderRight: "1px solid var(--line)" }}
        >
          <div className="p-2.5">
            <button
              className="af-btn af-btn-sm w-full flex items-center justify-center gap-1.5"
              onClick={startNewChat}
            >
              <Plus size={14} /> New chat
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-1.5 pb-2">
            <div
              className="px-2 pt-1 pb-1.5 text-[0.6875rem] font-semibold uppercase tracking-[0.06em]"
              style={{ color: "var(--ink-3)" }}
            >
              Threads
            </div>
            {sidebarThreads.map((t) => {
              const active = t.threadId === threadId;
              return (
                <button
                  key={t.threadId}
                  onClick={() => void setThreadId(t.threadId)}
                  className="w-full rounded-lg px-2.5 py-2 text-left mb-0.5"
                  style={{
                    background: active ? "var(--bg-soft)" : "transparent",
                    color: active ? "var(--ink)" : "var(--ink-3)",
                  }}
                >
                  <div className="text-[0.8125rem] font-medium truncate">
                    {threadLabel(t.threadId)}
                  </div>
                  {t.lastContent && (
                    <div className="text-[0.75rem] truncate" style={{ color: "var(--ink-3)" }}>
                      {t.lastContent}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-hidden">
          <div
            className="flex items-center justify-between px-4 py-3 flex-shrink-0"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <AgentAvatar agent={agent} size="sm" />
              <div className="min-w-0">
                <div
                  className="text-[0.875rem] font-medium leading-tight"
                  style={{ color: "var(--ink)" }}
                >
                  Chat with {agent.name}
                </div>
                <div className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
                  Try the agent here before connecting a messaging platform.
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span
                className="flex items-center gap-1.5 text-[0.75rem] font-medium"
                style={{ color: isLive ? "var(--ok, #16a34a)" : "var(--ink-3)" }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: isLive ? "var(--ok, #16a34a)" : "var(--ink-3)" }}
                />
                {isLive ? "Live" : streamStatus === "connecting" ? "Connecting…" : "Offline"}
              </span>
              <button
                type="button"
                className="af-btn af-btn-ghost af-btn-icon"
                onClick={() => setIsMaximized((v) => !v)}
                aria-label={isMaximized ? "Restore" : "Maximize"}
              >
                {isMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-hidden">
            <Thread key={threadId} />
          </div>
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
