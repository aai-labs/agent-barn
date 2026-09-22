"use client";

import { type ComponentProps, type ReactNode, useMemo, useState } from "react";
import { Pencil, Search, Share2, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toastError } from "@/shared/toast";

import { useMemoryGroups } from "@/features/memory-groups/hooks/use-memory-groups";

import type { MemoryScope } from "../hooks/use-agent-memory";
import type { AgentMemoryFacet, AgentMemoryItem } from "../schemas";
import { ShareMemoryToGroupDialog } from "./share-memory-to-group-dialog";

/** Only notable origins get a chip. Nearly every memory is plainly stated, so a
 *  chip saying so on every row is weight without signal — it would bury the shared
 *  and inferred ones that actually differ. `sharedAt` without a name means the
 *  source is gone. */
function OriginPill({ item, groupName }: { item: AgentMemoryItem; groupName?: string | null }) {
  const sharedFromGroup = Boolean(item.sharedFromGroupId);
  const shared = Boolean(item.sharedAt || sharedFromGroup);
  if (!shared && item.level !== "deductive") return null;

  const label = sharedFromGroup
    ? `Shared from ${groupName ?? "another group"}`
    : item.sharedAt
      ? "Shared in"
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
 *  that is redundant and omitted. `owner` reads as "you" — you talking to the agent
 *  through the app. `selfLabel` names the self-model owner (an agent's name); the
 *  group view has no single one, so a self-model row falls back to its peer id. */
function aboutLabel(item: AgentMemoryItem, selfLabel: string | null): string | null {
  if (item.observed === item.observer) return selfLabel ? `${selfLabel} itself` : item.observed;
  if (item.observed === "owner") return "you";
  return item.observed;
}

/** Sharing writes a fact under several peers so both runtimes' recall find it, so
 *  one fact can appear several times on a page. Collapse by content into a single
 *  row whose actions apply to every copy; a provenance-bearing copy wins the
 *  displayed row so the "shared" badge is never lost to a plain twin. */
type MemoryRow = { item: AgentMemoryItem; ids: string[] };

function collapse(items: AgentMemoryItem[]): MemoryRow[] {
  const rows = new Map<string, MemoryRow>();
  for (const item of items) {
    const existing = rows.get(item.content);
    if (existing) {
      existing.ids.push(item.id);
      // A provenance-bearing copy wins the displayed row so the "shared" badge is
      // never lost to a plain twin.
      if (!existing.item.sharedFromGroupId && item.sharedFromGroupId) existing.item = item;
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

type ShareConfig = {
  sourceGroupId: string;
  shareItem: ComponentProps<typeof ShareMemoryToGroupDialog>["shareItem"];
};

export type MemoryViewProps = {
  /** The items to show — the current page, or search results when searching. */
  items: AgentMemoryItem[];
  total: number;
  pageSize: number;
  facets: AgentMemoryFacet[];
  isLoading: boolean;
  error: unknown;

  page: number;
  onPageChange: (page: number) => void;
  peer: string | null;
  onSelectPeer: (peer: string | null) => void;

  search: string;
  onSearchChange: (value: string) => void;
  isSearching: boolean;
  searchPending: boolean;
  searchPlaceholder: string;

  /** Single-id operations; the view loops these over a collapsed row's copies. */
  forget: (memoryId: string) => Promise<unknown>;
  correct: (memoryId: string, content: string) => Promise<unknown>;
  isForgetting: boolean;
  isCorrecting: boolean;

  /** Names the self-model owner for the "· about X" label; null in the group view. */
  selfLabel: string | null;
  /** Whole-pool vs this-agent scope toggle; omit for the group view (always pool). */
  scope?: MemoryScope;
  onScopeChange?: (scope: MemoryScope) => void;
  /** Enables the per-item "Share to group" action. */
  share?: ShareConfig;

  errorText: string;
  emptyTitle: string;
  emptyBody: ReactNode;
};

/** The memory list surface — search, scope, peer filters, the collapsed item list
 *  with edit/forget/share, and pagination. Presentational and data-source agnostic:
 *  the per-Agent tab and the per-group page both render it with their own hooks. */
export function MemoryView(props: MemoryViewProps) {
  const {
    items,
    total,
    pageSize,
    facets,
    isLoading,
    error,
    page,
    onPageChange,
    peer,
    onSelectPeer,
    search,
    onSearchChange,
    isSearching,
    searchPending,
    searchPlaceholder,
    forget,
    correct,
    isForgetting,
    isCorrecting,
    selfLabel,
    scope,
    onScopeChange,
    share,
    errorText,
    emptyTitle,
    emptyBody,
  } = props;

  const [editingId, setEditingId] = useState<string | null>(null);
  const [sharing, setSharing] = useState<AgentMemoryItem | null>(null);
  const [draft, setDraft] = useState("");

  // Names for the "Shared from <group>" badge: reads carry only the id.
  const { groups } = useMemoryGroups();
  const groupNameById = useMemo(() => new Map(groups.map((g) => [g.id, g.name])), [groups]);

  const rows = useMemo(() => collapse(items), [items]);
  const everyoneCount = facets.reduce((sum, f) => sum + f.count, 0);
  const pageCount = Math.ceil(total / pageSize);

  const onSaveCorrection = async (row: MemoryRow) => {
    try {
      for (const id of row.ids) await correct(id, draft);
      setEditingId(null);
      toast.success("Memory updated.");
    } catch (err) {
      toastError(err, "Could not update this memory.");
    }
  };

  const onForget = async (row: MemoryRow) => {
    try {
      for (const id of row.ids) await forget(id);
      toast.success("Memory forgotten.");
    } catch (err) {
      toastError(err, "Could not forget this memory.");
    }
  };

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorText}</AlertDescription>
      </Alert>
    );
  }

  const chips = [
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
      <div className="relative w-full sm:max-w-sm">
        <Search
          size={15}
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
          style={{ color: "var(--ink-4)" }}
        />
        <Input
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
        {search.length > 0 && (
          <button
            type="button"
            onClick={() => onSearchChange("")}
            aria-label="Clear search"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1 transition-colors duration-150 hover:bg-[var(--bg-sunken)]"
            style={{ color: "var(--ink-4)" }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Scope: the whole group's shared memory vs. only what this agent added. */}
      {scope && onScopeChange && !isSearching && (total > 0 || facets.length > 0 || scope === "mine") && (
        <div
          className="inline-flex rounded-lg p-0.5"
          role="group"
          aria-label="Whose memory to show"
          style={{ background: "var(--bg-sunken)", border: "1px solid var(--line)" }}
        >
          {(
            [
              { value: "pool", label: "Whole group" },
              { value: "mine", label: "This agent" },
            ] as const
          ).map((option) => {
            const active = scope === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => onScopeChange(option.value)}
                aria-pressed={active}
                className="rounded-md px-3 py-1 text-[0.8125rem] font-medium transition-colors duration-150"
                style={
                  active
                    ? {
                        background: "var(--bg-elev)",
                        color: "var(--ink)",
                        boxShadow: "var(--shadow-sm, 0 1px 2px rgb(0 0 0 / 0.06))",
                      }
                    : { background: "transparent", color: "var(--ink-3)" }
                }
              >
                {option.label}
              </button>
            );
          })}
        </div>
      )}

      {/* Peer facets. Hidden while searching, and when there is only Everyone. */}
      {!isSearching && facets.length > 1 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by who the memory is about">
          {chips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => onSelectPeer(chip.key === "__everyone" ? null : chip.key)}
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
          searchPending ? (
            "Searching…"
          ) : (
            `${rows.length} matching ${rows.length === 1 ? "memory" : "memories"}`
          )
        ) : pageCount > 1 ? (
          `Page ${page} of ${pageCount} · ${total} ${total === 1 ? "memory" : "memories"}`
        ) : (
          `${total} ${total === 1 ? "memory" : "memories"}`
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
            {emptyTitle}
          </p>
          <p className="mx-auto mt-1.5 max-w-sm text-sm" style={{ color: "var(--ink-3)" }}>
            {emptyBody}
          </p>
        </div>
      ) : rows.length === 0 ? (
        <div
          className="rounded-lg px-6 py-12 text-center"
          style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)" }}
        >
          <p className="text-sm font-medium" style={{ color: "var(--ink-2)" }}>
            {isSearching ? "No memories match that search" : "Nothing here"}
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-3)" }}>
            {isSearching ? (
              "Try fewer or broader words."
            ) : (
              <button type="button" onClick={() => onSelectPeer(null)} className="underline underline-offset-2">
                Show everyone
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
            const about = peer === null ? aboutLabel(item, selfLabel) : null;
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
                        disabled={isCorrecting || draft.trim().length === 0}
                      >
                        {isCorrecting ? "Saving…" : "Save"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                        Cancel
                      </Button>
                      <span className="text-xs" style={{ color: "var(--ink-4)" }}>
                        The agents will remember your version instead.
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
                        <OriginPill
                          item={item}
                          groupName={item.sharedFromGroupId ? groupNameById.get(item.sharedFromGroupId) : null}
                        />
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
                      {share && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label="Share this memory with another group"
                              onClick={() => setSharing(item)}
                            >
                              <Share2 size={14} />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Share with another group</TooltipContent>
                        </Tooltip>
                      )}
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label="Forget this memory"
                            onClick={() => void onForget(row)}
                            disabled={isForgetting}
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
          <Button size="sm" variant="outline" disabled={page === 1} onClick={() => onPageChange(page - 1)}>
            Previous
          </Button>
          <span className="text-sm" style={{ color: "var(--ink-3)" }}>
            Page {page} of {pageCount}
          </span>
          <Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
            Next
          </Button>
        </div>
      )}

      {sharing && share && (
        <ShareMemoryToGroupDialog
          open
          onOpenChange={(next) => !next && setSharing(null)}
          sourceGroupId={share.sourceGroupId}
          memoryId={sharing.id}
          content={sharing.content}
          shareItem={share.shareItem}
        />
      )}
    </div>
  );
}
