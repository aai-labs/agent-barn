"use client";

import { useMemo, useState } from "react";
import { Bot, Pencil, Search, Share2, Trash2, UserRound, X } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toastError } from "@/shared/toast";

import { useAgentMemory, useAgentMemorySearch } from "../hooks/use-agent-memory";
import type { AgentMemoryItem } from "../schemas";
import { ShareMemoryDialog } from "./share-memory-dialog";

const PAGE_SIZE = 50;

/** Honcho derives a conclusion from every message, including ones that only record
 *  that something was asked — "operator asked where the runbooks live". On a real
 *  agent these outnumber actual knowledge, so the view offers to set them aside.
 *  A heuristic on wording, not a Honcho distinction: it hides rows, never deletes
 *  them, and "All" is one click away. */
const CONVERSATIONAL_NOISE =
  /\b(asked|instructed|repeatedly asks|querying|as referenced|as evidenced)\b/i;

function isConversationalNoise(item: AgentMemoryItem): boolean {
  return CONVERSATIONAL_NOISE.test(item.content);
}

/** Group by the peer an item is *about*, since that is the question an owner has:
 *  "what does this Agent think it knows about me / about itself". */
function groupByObserved(items: AgentMemoryItem[]): [string, AgentMemoryItem[]][] {
  const groups = new Map<string, AgentMemoryItem[]>();
  for (const item of items) {
    const existing = groups.get(item.observed);
    if (existing) existing.push(item);
    else groups.set(item.observed, [item]);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
}

/** `owner` is the plugin's bucket for messages that arrived without a sender
 *  identity — cron runs, heartbeats, direct API calls — not a person. Labelling
 *  it as a user would be actively misleading. `shared-memory` is residue from an
 *  earlier sharing implementation that wrote a synthetic peer; nothing creates it
 *  now, but rows written back then still exist. */
function describePeer(peer: string, agentName: string): { label: string; self: boolean } {
  if (peer === "owner") return { label: "From messages with no sender", self: false };
  if (peer === "shared-memory") return { label: "Shared with this agent", self: false };
  if (peer.startsWith("agent-")) return { label: `What ${agentName} knows`, self: true };
  return { label: `About ${peer}`, self: false };
}

/** Honcho stores the same fact once per (observer, observed) pair, so one thing the
 *  agent knows about a person arrives twice — the agent's view of them and their own
 *  self-model. Both land in the same group, where they read as a rendering bug. They
 *  are collapsed into one row that acts on every copy, rather than hidden: dropping a
 *  copy from view would leave Forget removing one of two identical rows. */
type MemoryEntry = { item: AgentMemoryItem; ids: string[] };

function collapseIdentical(items: AgentMemoryItem[]): MemoryEntry[] {
  const entries = new Map<string, MemoryEntry>();
  for (const item of items) {
    const existing = entries.get(item.content);
    // Keep whichever copy carries provenance, so collapsing never loses the badge.
    if (existing) {
      existing.ids.push(item.id);
      if (!existing.item.sharedFrom && item.sharedFrom) existing.item = item;
    } else {
      entries.set(item.content, { item, ids: [item.id] });
    }
  }
  return [...entries.values()];
}

/** A shared fact is written onto the destination's own self-model, so it sits in
 *  the same place as everything the agent worked out for itself. Without saying
 *  where it came from, the view presents a fact the agent was handed as one it
 *  reasoned its way to. `sharedAt` without a name means the source agent is gone.
 *
 *  Only the notable origins get a chip. Nearly every memory is "stated", so a chip
 *  saying so on every row is weight without information — it would bury the two that
 *  actually differ. */
function OriginPill({ item }: { item: AgentMemoryItem }) {
  const shared = Boolean(item.sharedFrom || item.sharedAt);
  if (!shared && item.level !== "deductive") return null;

  const label = item.sharedFrom
    ? `Shared by ${item.sharedFrom}`
    : item.sharedAt
      ? "Shared by a deleted agent"
      : "Inferred";

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.75rem] whitespace-nowrap"
      style={
        shared
          ? { background: "var(--accent-soft)", border: "1px solid var(--accent-soft)", color: "var(--accent-ink)" }
          : { background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-3)" }
      }
    >
      {shared && <Share2 size={12} aria-hidden />}
      {label}
    </span>
  );
}

function MemoryRowSkeleton() {
  return (
    <div className="px-4 py-3.5">
      <Skeleton className="h-4 w-[70%]" />
      <Skeleton className="mt-2.5 h-3 w-40" />
    </div>
  );
}

export function AgentMemoryPage({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [page, setPage] = useState(1);
  const { memory, isLoading, error, forget, correct, share } = useAgentMemory(agentId, page, PAGE_SIZE);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [sharing, setSharing] = useState<AgentMemoryItem | null>(null);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [factsOnly, setFactsOnly] = useState(false);
  const searchQuery = useAgentMemorySearch(agentId, search);
  const isSearching = search.trim().length > 2;

  const loaded = useMemo(
    () => (isSearching ? (searchQuery.data ?? []) : (memory?.items ?? [])),
    [isSearching, searchQuery.data, memory?.items],
  );
  const items = useMemo(
    () => (factsOnly ? loaded.filter((item) => !isConversationalNoise(item)) : loaded),
    [loaded, factsOnly],
  );
  const setAside = loaded.length - items.length;
  const total = memory?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  // A row can stand for the same fact stored under more than one peer pair, so both
  // actions apply to every copy — correcting one and leaving its twin behind would
  // put the agent back where it started.
  const onSaveCorrection = async (entry: MemoryEntry) => {
    try {
      for (const id of entry.ids) {
        await correct.mutateAsync({ memoryId: id, content: draft });
      }
      // The replacement is a new item, so there is nothing to keep editing.
      setEditingId(null);
      toast.success("Memory updated.");
    } catch (err) {
      toastError(err, "Could not update this memory.");
    }
  };

  const onForget = async (entry: MemoryEntry) => {
    try {
      for (const id of entry.ids) {
        await forget.mutateAsync(id);
      }
      toast.success("Memory forgotten.");
    } catch (err) {
      toastError(err, "Could not forget this memory.");
    }
  };

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          Could not load this agent&apos;s memory. Try again in a moment.
        </AlertDescription>
      </Alert>
    );
  }

  const controls = (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="relative w-full sm:max-w-sm">
        <Search
          size={15}
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
          style={{ color: "var(--ink-4)" }}
        />
        <Input
          placeholder="Search this agent's memory…"
          aria-label="Search this agent's memory"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
        {search.length > 0 && (
          <button
            type="button"
            onClick={() => setSearch("")}
            aria-label="Clear search"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1 transition-colors duration-150 hover:bg-[var(--bg-sunken)]"
            style={{ color: "var(--ink-4)" }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div
        className="inline-flex shrink-0 self-start rounded-full p-0.5 sm:self-auto"
        style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}
        role="group"
        aria-label="Filter memories"
      >
        {(
          [
            ["All", false],
            ["Facts only", true],
          ] as const
        ).map(([label, value]) => (
          <button
            key={label}
            type="button"
            onClick={() => setFactsOnly(value)}
            aria-pressed={factsOnly === value}
            className="rounded-full px-3 py-1 text-[0.8125rem] transition-colors duration-150"
            style={
              factsOnly === value
                ? { background: "var(--bg-elev)", color: "var(--ink)", boxShadow: "var(--shadow-sm)" }
                : { color: "var(--ink-3)" }
            }
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      {controls}

      <p className="text-sm" style={{ color: "var(--ink-3)" }}>
        {isSearching ? (
          searchQuery.isPending ? (
            "Searching…"
          ) : (
            `${items.length} matching ${items.length === 1 ? "memory" : "memories"}`
          )
        ) : (
          <>
            {/* Counts below are for this page, so say which page they describe rather
                than pairing a page of rows with a total that does not match them. */}
            {pageCount > 1
              ? `Showing ${loaded.length} of ${total} memories`
              : `${total} ${total === 1 ? "memory" : "memories"}`}
          </>
        )}
        {setAside > 0 && (
          <>
            {" · "}
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => setFactsOnly(false)}
                  className="underline decoration-dotted underline-offset-2"
                >
                  {setAside} set aside
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                Notes about questions that were asked, rather than anything the agent learned. Hidden here,
                not deleted.
              </TooltipContent>
            </Tooltip>
          </>
        )}
      </p>

      {isLoading ? (
        <div
          className="divide-y overflow-hidden rounded-lg"
          style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", borderColor: "var(--line)" }}
        >
          {Array.from({ length: 4 }, (_, i) => (
            <MemoryRowSkeleton key={i} />
          ))}
        </div>
      ) : total === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--ink-2)" }}>
            Nothing learned yet
          </p>
          <p className="mx-auto mt-1.5 max-w-sm text-sm" style={{ color: "var(--ink-3)" }}>
            Memories appear here after {agentName} has held a conversation. You can then correct, forget, or
            share any of them.
          </p>
        </div>
      ) : items.length === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--ink-2)" }}>
            {isSearching ? "No memories match that search" : "Nothing left after filtering"}
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-3)" }}>
            {isSearching ? (
              "Try fewer or broader words."
            ) : (
              <button type="button" onClick={() => setFactsOnly(false)} className="underline underline-offset-2">
                Show all {loaded.length} memories
              </button>
            )}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groupByObserved(items).map(([observed, rawGroup]) => {
            const peer = describePeer(observed, agentName);
            const PeerIcon = peer.self ? Bot : UserRound;
            const group = collapseIdentical(rawGroup);
            return (
              <section key={observed} className="space-y-2">
                <header className="flex items-center gap-2 px-0.5">
                  <PeerIcon size={14} aria-hidden style={{ color: "var(--ink-4)" }} />
                  <h3
                    className="text-[0.8125rem] font-medium tracking-[0.02em] uppercase"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {peer.label}
                  </h3>
                  <span className="text-[0.8125rem]" style={{ color: "var(--ink-4)" }}>
                    {group.length}
                  </span>
                </header>

                <div
                  className="divide-y overflow-hidden rounded-lg"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
                >
                  {group.map((entry) => {
                    const item = entry.item;
                    return (
                    <div
                      key={item.id}
                      className="group/row px-4 py-3.5 transition-colors duration-150 hover:bg-[var(--bg-soft)] focus-within:bg-[var(--bg-soft)]"
                    >
                      {editingId === item.id ? (
                        <div className="space-y-2.5">
                          <Textarea
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            rows={3}
                            aria-label="Memory content"
                            autoFocus
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              onClick={() => void onSaveCorrection(entry)}
                              disabled={correct.isPending || draft.trim().length === 0}
                            >
                              {correct.isPending ? "Saving…" : "Save"}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                              Cancel
                            </Button>
                            <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                              The agent will remember your version instead.
                            </span>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 space-y-1.5">
                            <p className="max-w-[68ch] text-sm" style={{ color: "var(--ink)" }}>
                              {item.content}
                            </p>
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <OriginPill item={item} />
                              {item.createdAt && (
                                <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                                  {new Date(item.createdAt).toLocaleDateString(undefined, {
                                    month: "short",
                                    day: "numeric",
                                  })}
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Opacity, not visibility: the buttons stay in the tab order and
                              reveal on keyboard focus as well as hover. */}
                          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-150 group-hover/row:opacity-100 group-focus-within/row:opacity-100">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Edit this memory"
                                  onClick={() => {
                                    setEditingId(item.id);
                                    setDraft(item.content);
                                  }}
                                >
                                  <Pencil size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Edit</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Share this memory with another agent"
                                  onClick={() => setSharing(item)}
                                >
                                  <Share2 size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Share with another agent</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Forget this memory"
                                  onClick={() => void onForget(entry)}
                                  disabled={forget.isPending}
                                >
                                  <Trash2 size={14} />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Forget</TooltipContent>
                            </Tooltip>
                          </div>
                        </div>
                      )}
                    </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {!isSearching && pageCount > 1 && (
        <div className="flex items-center justify-between gap-3">
          <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="text-sm" style={{ color: "var(--ink-3)" }}>
            Page {page} of {pageCount}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page >= pageCount}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {sharing && (
        <ShareMemoryDialog
          open
          onOpenChange={(next) => !next && setSharing(null)}
          sourceAgentId={agentId}
          initialContent={sharing.content}
          share={share}
        />
      )}
    </div>
  );
}
