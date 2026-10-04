"use client";

import { useState, type FormEvent } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { Pagination } from "@/features/agents/components/pagination";
import type { Agent } from "@/features/agents/schemas";
import { formatDate } from "@/shared/date";

import { useMemoryItems } from "../hooks/use-memory-items";
import type { MemoryItem } from "../schemas";
import { MEMORY_ITEMS_PAGE_SIZE, MEMORY_TYPE_LABEL, ORGANIZATION_MEMORY_LABEL } from "../utils";

function Pill({ children, tone = "plain" }: { children: string; tone?: "plain" | "shared" }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[0.72rem] font-medium"
      style={{
        background: tone === "shared" ? "var(--accent-soft)" : "var(--bg-soft)",
        border: "1px solid var(--line)",
        color: "var(--ink-3)",
      }}
    >
      {children}
    </span>
  );
}

function MemoryRow({ item }: { item: MemoryItem }) {
  return (
    <li className="px-0 py-3.5" style={{ borderBottom: "1px solid var(--line)" }}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Pill>{MEMORY_TYPE_LABEL[item.type]}</Pill>
        {item.shared ? <Pill tone="shared">{`Shared · ${ORGANIZATION_MEMORY_LABEL}`}</Pill> : <Pill>Private</Pill>}
        <span className="text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
          {item.mentionedAt ? `Mentioned ${formatDate(item.mentionedAt)}` : "No date recorded"}
        </span>
      </div>
      {/* Rendered as text, never markup: memory content comes from conversations. */}
      <p
        className="m-0 whitespace-pre-wrap break-words text-[0.9rem] leading-relaxed"
        style={{ color: "var(--ink)" }}
      >
        {item.text}
      </p>
    </li>
  );
}

/**
 * Shared human viewer; callers supply either Agent activity permission or
 * Organization memory administration permission. Agent grants do not govern this list.
 */
export function MemoryItemsViewer({ agent, enabled }: { agent?: Agent; enabled: boolean }) {
  const organization = !agent;
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { items, total, isLoading, isFetching, error, refetch } = useMemoryItems(agent?.id, {
    search,
    page,
    enabled,
  });

  if (!enabled) return null;

  const totalPages = Math.max(1, Math.ceil(total / MEMORY_ITEMS_PAGE_SIZE));

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setSearch(searchInput.trim());
    setPage(1);
  }

  return (
    <section aria-label="Saved memories">
      <p className="mb-4 mt-0 max-w-3xl text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
        {organization
          ? "Shared memories saved for this Organization by its Agents. Private Agent memories are excluded. Revoking an Agent's access keeps previously saved memories. This list is read-only."
          : `What ${agent.name} saved, including Organization Memory it wrote. This is saved history, not a list of its current access. Revoking the Agent's Organization Memory access keeps these records; your permission to view them is separate. This list is read-only.`}
        {!organization && !agent.memoryEnabled && " Saved history stays available while memory is off."}
      </p>

      <form className="mb-4 flex items-center gap-2.5" role="search" onSubmit={submitSearch}>
        <input
          className="af-input flex-1"
          type="search"
          placeholder="Search saved memories…"
          aria-label="Search saved memories"
          maxLength={200}
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
        <button type="submit" className="af-btn">
          Search
        </button>
        {search && (
          <button
            type="button"
            className="af-btn af-btn-ghost"
            onClick={() => {
              setSearchInput("");
              setSearch("");
              setPage(1);
            }}
          >
            Clear
          </button>
        )}
      </form>

      {isLoading && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          Loading memories…
        </div>
      )}

      {error && (
        <AppErrorState
          error={error}
          title={organization ? "We couldn't load Organization Memory" : "We couldn't load this Agent's memories"}
          description="Saved memories are unavailable right now."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-0 p-0"
        />
      )}

      {!isLoading && !error && items.length === 0 && (
        <div
          className="flex flex-col items-center justify-center rounded-2xl py-10 text-center"
          style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
        >
          <div className="mb-1 text-[0.9375rem] font-medium" style={{ color: "var(--ink)" }}>
            {page > 1 ? "No memories on this page" : search ? "No saved memories match" : "Nothing saved yet"}
          </div>
          <div className="text-[0.844rem]">
            {page > 1
              ? "Saved memories may have changed. Return to a previous page."
              : search
              ? "Try a different search."
              : organization
                ? "Agents with Read and write access can explicitly save Organization Memory."
                : agent.memoryEnabled
                  ? `${agent.name} saves memories as it talks with people.`
                  : "Long-term memory is off for this Agent, and it has not saved anything."}
          </div>
        </div>
      )}

      {!error && items.length > 0 && (
        <>
          <div className="mb-1 text-[0.78rem]" style={{ color: "var(--ink-4)" }} aria-live="polite">
            {total} {total === 1 ? "memory" : "memories"}
            {isFetching ? " · Updating…" : ""}
          </div>
          <ul className="m-0 list-none p-0">
            {items.map((item) => (
              <MemoryRow key={item.id} item={item} />
            ))}
          </ul>
        </>
      )}
      {!error && !isLoading && (items.length > 0 || page > 1) && (
        <div className="pt-4">
          <Pagination page={page} totalPages={Math.max(page, totalPages)} onPageChange={setPage} />
        </div>
      )}
    </section>
  );
}
