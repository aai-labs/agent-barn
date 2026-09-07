"use client";

import { useMemo, useState } from "react";
import { Pencil, Search, Share2, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toastError } from "@/shared/toast";

import { useAgentMemory, useAgentMemoryFacets, useAgentMemorySearch } from "../hooks/use-agent-memory";
import type { AgentMemoryFacet, AgentMemoryItem } from "../schemas";
import { ShareMemoryDialog } from "./share-memory-dialog";

const PAGE_SIZE = 50;

/** Honcho derives a conclusion from every message, including ones that only record
 *  that something was asked — "operator asked where the runbooks live". On a real
 *  agent these outnumber actual knowledge, so the view offers to set them aside.
 *  A heuristic on wording, not a Honcho distinction: it hides rows, never deletes
 *  them, and "All" is one click away. */
const QUESTION_NOTE = /\b(asked|instructed|repeatedly asks|querying)\b/i;

function isQuestionNote(item: AgentMemoryItem): boolean {
  return QUESTION_NOTE.test(item.content);
}

/** Only notable origins get a chip. Nearly every memory is plainly stated, so a
 *  chip saying so on every row is weight without signal — it would bury the shared
 *  and inferred ones that actually differ. `sharedAt` without a name means the
 *  source agent has been deleted. */
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

/** Under "Everyone" a row needs to say who it is about; under a single peer filter
 *  that is redundant and omitted. `owner` reads as "you" for the same reason the
 *  facet does — it is you talking to the agent through the app. */
function aboutLabel(item: AgentMemoryItem, agentName: string): string | null {
  if (item.observed === item.observer) return `${agentName} itself`;
  if (item.observed === "owner") return "you";
  return item.observed;
}

/** Sharing deliberately writes a fact under the agent's self-model and under each
 *  person it knows, so both runtimes' recall can find it — which means one fact can
 *  appear several times on a page. Collapse by content into a single row whose
 *  actions apply to every copy; forgetting or correcting one and leaving its twins
 *  would put the agent back where it started. Provenance-bearing copies win the
 *  displayed row so the "shared" badge is never lost to a plain twin. */
type MemoryRow = { item: AgentMemoryItem; ids: string[] };

function collapse(items: AgentMemoryItem[]): MemoryRow[] {
  const rows = new Map<string, MemoryRow>();
  for (const item of items) {
    const existing = rows.get(item.content);
    if (existing) {
      existing.ids.push(item.id);
      if (!existing.item.sharedFrom && item.sharedFrom) existing.item = item;
    } else {
      rows.set(item.content, { item, ids: [item.id] });
    }
  }
  return [...rows.values()];
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
  // null = the "Everyone" facet; otherwise a peer id sent to the API as `observed`.
  const [peer, setPeer] = useState<string | null>(null);
  const { memory, isLoading, error, forget, correct, share } = useAgentMemory(agentId, page, PAGE_SIZE, peer);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [sharing, setSharing] = useState<AgentMemoryItem | null>(null);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [factsOnly, setFactsOnly] = useState(false);
  const searchQuery = useAgentMemorySearch(agentId, search);
  const isSearching = search.trim().length > 2;

  // Facets come from their own cached query, not the paged list, so the chips stay
  // put while a filter is active — picking a peer must not remove the control
  // needed to pick another or return to Everyone.
  const facets = useAgentMemoryFacets(agentId);
  const everyoneCount = facets.reduce((sum, f) => sum + f.count, 0);

  const loaded = useMemo(
    () => (isSearching ? (searchQuery.data ?? []) : (memory?.items ?? [])),
    [isSearching, searchQuery.data, memory?.items],
  );
  const filtered = useMemo(
    () => (factsOnly ? loaded.filter((item) => !isQuestionNote(item)) : loaded),
    [loaded, factsOnly],
  );
  const rows = useMemo(() => collapse(filtered), [filtered]);
  const setAside = loaded.length - filtered.length;
  const total = memory?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  const selectPeer = (next: string | null) => {
    setPeer(next);
    setPage(1);
  };

  // A displayed row can stand for several stored copies of the same fact, so both
  // actions apply to every copy — correcting or forgetting one and leaving its
  // twins would leave the agent still holding the old version.
  const onSaveCorrection = async (row: MemoryRow) => {
    try {
      for (const id of row.ids) await correct.mutateAsync({ memoryId: id, content: draft });
      setEditingId(null);
      toast.success("Memory updated.");
    } catch (err) {
      toastError(err, "Could not update this memory.");
    }
  };

  const onForget = async (row: MemoryRow) => {
    try {
      for (const id of row.ids) await forget.mutateAsync(id);
      toast.success("Memory forgotten.");
    } catch (err) {
      toastError(err, "Could not forget this memory.");
    }
  };

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>Could not load this agent&apos;s memory. Try again in a moment.</AlertDescription>
      </Alert>
    );
  }

  // Facets come only with the unfiltered response, so a synthetic "Everyone" chip
  // leads and the peer chips follow in the order the API sorted them.
  const chips: { key: string; label: string; count: number; active: boolean }[] = [
    { key: "__everyone", label: "Everyone", count: everyoneCount, active: peer === null },
    ...facets.map((f: AgentMemoryFacet) => ({
      key: f.peer,
      label: f.label,
      count: f.count,
      active: peer === f.peer,
    })),
  ];

  return (
    <div className="space-y-5">
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
          aria-label="Filter by kind"
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

      {/* Peer facets. Hidden while searching, which spans every peer already, and
          when there is only the Everyone chip (a single-peer agent needs no filter). */}
      {!isSearching && facets.length > 1 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by who the memory is about">
          {chips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => selectPeer(chip.key === "__everyone" ? null : chip.key)}
              aria-pressed={chip.active}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[0.8125rem] transition-colors duration-150"
              style={
                chip.active
                  ? { background: "var(--ink)", color: "var(--bg-elev)", border: "1px solid var(--ink)" }
                  : { background: "var(--bg-elev)", color: "var(--ink-2)", border: "1px solid var(--line)" }
              }
            >
              {chip.label}
              <span style={{ color: chip.active ? "var(--bg-sunken)" : "var(--ink-4)" }}>{chip.count}</span>
            </button>
          ))}
        </div>
      )}

      <p className="text-sm" style={{ color: "var(--ink-3)" }}>
        {isSearching ? (
          searchQuery.isPending ? (
            "Searching…"
          ) : (
            `${rows.length} matching ${rows.length === 1 ? "memory" : "memories"}`
          )
        ) : pageCount > 1 ? (
          `Page ${page} of ${pageCount} · ${total} ${total === 1 ? "memory" : "memories"}`
        ) : (
          `${total} ${total === 1 ? "memory" : "memories"}`
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
                  {setAside} on this page hidden
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
          style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
        >
          {Array.from({ length: 5 }, (_, i) => (
            <MemoryRowSkeleton key={i} />
          ))}
        </div>
      ) : total === 0 && !isSearching ? (
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
      ) : rows.length === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--ink-2)" }}>
            {isSearching ? "No memories match that search" : "Nothing on this page after filtering"}
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-3)" }}>
            {isSearching ? (
              "Try fewer or broader words."
            ) : (
              <button type="button" onClick={() => setFactsOnly(false)} className="underline underline-offset-2">
                Show everything on this page
              </button>
            )}
          </p>
        </div>
      ) : (
        <div
          className="divide-y overflow-hidden rounded-lg"
          style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
        >
          {rows.map((row) => {
            const item = row.item;
            const about = peer === null ? aboutLabel(item, agentName) : null;
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
                        onClick={() => void onSaveCorrection(row)}
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
                        {about && (
                          <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                            · about {about}
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
                            onClick={() => void onForget(row)}
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
