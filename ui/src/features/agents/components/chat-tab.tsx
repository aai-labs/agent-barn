"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, Maximize2, MoreHorizontal, Minimize2, Pencil, Plus } from "lucide-react";
import { useQueryState, parseAsString } from "nuqs";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { Badge } from "@/components/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import type { Agent, WebChatMessage } from "../schemas";
import { MAIN_THREAD_ID, useWebChat } from "../hooks/use-web-chat";
import { useWebChatThreads } from "../hooks/use-web-chat-threads";
import { AgentAvatar } from "./agent-avatar";

interface ChatTabProps {
  agent: Agent;
  isAgentWorking: boolean;
}

function convertMessage(message: WebChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.direction === "OUTBOUND" ? "assistant" : "user",
    content: [{ type: "text", text: message.content }],
    createdAt: new Date(message.occurredAt),
  };
}

interface ChatThreadProps {
  agentName: string;
  messages: WebChatMessage[];
  isAgentWorking: boolean;
  isAwaitingReply: boolean;
  sendMessage: (text: string) => Promise<void>;
  stopGeneration: () => Promise<void>;
  onSent: () => void;
}

function ChatThread({
  agentName,
  messages,
  isAgentWorking,
  isAwaitingReply,
  sendMessage,
  stopGeneration,
  onSent,
}: ChatThreadProps) {
  const runtime = useExternalStoreRuntime<WebChatMessage>({
    messages,
    isDisabled: !isAgentWorking,
    isRunning: isAgentWorking && isAwaitingReply,
    convertMessage,
    onNew: async (message) => {
      const part = message.content.find((candidate) => candidate.type === "text");
      if (!part || part.type !== "text") return;
      await sendMessage(part.text);
      onSent();
    },
    onCancel: async () => {
      await stopGeneration();
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread workingMessage={`${agentName} is working`} />
    </AssistantRuntimeProvider>
  );
}

function fallbackTitle(threadId: string) {
  return threadId === MAIN_THREAD_ID ? "Main chat" : "New chat";
}

interface SidebarThread {
  threadId: string;
  title: string;
  lastContent: string | null;
}

interface ThreadListItemProps {
  thread: SidebarThread;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onArchive: () => void;
}

function ThreadListItem({ thread, active, onSelect, onRename, onArchive }: ThreadListItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(thread.title);
  const [confirmArchiveOpen, setConfirmArchiveOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function startEditing() {
    setDraft(thread.title);
    setIsEditing(true);
  }

  function commitEdit() {
    const trimmed = draft.trim();
    setIsEditing(false);
    if (trimmed && trimmed !== thread.title) onRename(trimmed);
  }

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitEdit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commitEdit();
          } else if (e.key === "Escape") {
            setIsEditing(false);
          }
        }}
        className="w-full rounded-lg px-2.5 py-2 mb-0.5 text-[0.8125rem] font-medium outline-none"
        style={{ background: "var(--bg-soft)", color: "var(--ink)", border: "1px solid var(--line)" }}
      />
    );
  }

  return (
    <div
      className="group relative w-full rounded-lg mb-0.5"
      style={{ background: active ? "var(--bg-soft)" : "transparent" }}
    >
      <button
        onClick={onSelect}
        className="w-full rounded-lg px-2.5 py-2 pr-8 text-left"
        style={{ color: active ? "var(--ink)" : "var(--ink-3)" }}
      >
        <div className="text-[0.8125rem] font-medium truncate">{thread.title}</div>
        {thread.lastContent && (
          <div className="text-[0.75rem] truncate" style={{ color: "var(--ink-3)" }}>
            {thread.lastContent}
          </div>
        )}
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1 opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100"
            style={{ color: "var(--ink-3)" }}
            aria-label="Thread options"
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal size={14} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onSelect={startEditing}>
            <Pencil size={14} /> Rename
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onSelect={() => setConfirmArchiveOpen(true)}>
            <Archive size={14} /> Archive
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <AlertDialog open={confirmArchiveOpen} onOpenChange={setConfirmArchiveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Archive &ldquo;{thread.title}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              It&rsquo;ll disappear from this list, but the conversation is kept — send a new
              message on it later and it comes right back.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={onArchive}>
              Archive
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function ChatTab({ agent, isAgentWorking }: ChatTabProps) {
  const [threadId, setThreadId] = useQueryState(
    "thread",
    parseAsString.withDefault(MAIN_THREAD_ID).withOptions({ history: "replace" }),
  );

  const { messages, sendMessage, stopGeneration, isAwaitingReply, streamStatus } = useWebChat(
    agent.id,
    threadId,
    true,
  );
  const {
    threads,
    refetch: refetchThreads,
    renameThread,
    deleteThread,
  } = useWebChatThreads(agent.id, true);

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

  const isLive = streamStatus === "streaming";

  // `threads` is already most-recent-first. A brand-new thread (no messages
  // sent yet) isn't in that list, so it goes first — it's the newest one, by
  // definition more recent than anything with a message already in it. Main
  // chat still always appears (even with zero messages, for discoverability
  // of the default thread), but only pinned to the end if nothing else put
  // it earlier.
  const sidebarThreads = useMemo<SidebarThread[]>(() => {
    const known = new Map(threads.map((t) => [t.threadId, t]));
    const ids = [...threads.map((t) => t.threadId)];
    if (!known.has(threadId)) ids.unshift(threadId);
    if (!known.has(MAIN_THREAD_ID) && threadId !== MAIN_THREAD_ID) ids.push(MAIN_THREAD_ID);
    return ids.map((id) => {
      const meta = known.get(id);
      return {
        threadId: id,
        title: meta?.title ?? fallbackTitle(id),
        lastContent: meta?.lastContent ?? null,
      };
    });
  }, [threads, threadId]);

  function handleArchive(archivedId: string) {
    void deleteThread(archivedId).then(() => {
      if (archivedId === threadId) void setThreadId(MAIN_THREAD_ID);
    });
  }

  return (
      <div
        className={cn(
          "flex overflow-hidden",
          isMaximized ? "fixed inset-4 z-50 rounded-2xl shadow-2xl" : "rounded-2xl",
        )}
        style={{
          border: "1px solid var(--line)",
          height: isMaximized ? undefined : "min(760px, 80vh)",
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
            {sidebarThreads.map((t) => (
              <ThreadListItem
                key={t.threadId}
                thread={t}
                active={t.threadId === threadId}
                onSelect={() => void setThreadId(t.threadId)}
                onRename={(title) => void renameThread(t.threadId, title)}
                onArchive={() => handleArchive(t.threadId)}
              />
            ))}
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
                <div className="flex items-center gap-2 leading-tight">
                  <span className="text-[0.875rem] font-medium" style={{ color: "var(--ink)" }}>
                    Chat with {agent.name}
                  </span>
                  <Badge variant="warn" title="Web Chat is under active development and may change or break without notice.">
                    Experimental
                  </Badge>
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
                title="Whether this panel is receiving new messages in real time — independent of whether the Agent itself is running or reachable."
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: isLive ? "var(--ok, #16a34a)" : "var(--ink-3)" }}
                />
                {isLive
                  ? "Live updates"
                  : streamStatus === "connecting"
                    ? "Connecting…"
                    : "Updates paused"}
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
            <ChatThread
              key={threadId}
              agentName={agent.name}
              messages={messages}
              isAgentWorking={isAgentWorking}
              isAwaitingReply={isAwaitingReply}
              sendMessage={sendMessage}
              stopGeneration={stopGeneration}
              onSent={() => void refetchThreads()}
            />
          </div>
        </div>
      </div>
  );
}
