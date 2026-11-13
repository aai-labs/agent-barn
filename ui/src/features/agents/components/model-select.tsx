"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { CheckIcon, SearchIcon } from "@/components/icons";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useModels } from "../hooks/use-models";
import type { ModelOption } from "../schemas";

const MENU_GAP = 4;
const VIEWPORT_MARGIN = 8;

interface ModelSelectProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function ModelSelect({
  value,
  onChange,
  disabled,
  "aria-label": ariaLabel = "Model",
}: ModelSelectProps) {
  const { models } = useModels();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep the current value selectable even if it falls outside the allowlist
  // (e.g. an existing agent on a model that's no longer offered).
  const allOptions: ModelOption[] = useMemo(
    () =>
      value && !models.some((m) => m.value === value)
        ? [{ value, label: value }, ...models]
        : models,
    [models, value],
  );

  const selectedLabel =
    allOptions.find((m) => m.value === value)?.label ?? value ?? "Select a model…";

  // Case-insensitive substring search across label + value so "gpt" matches
  // "GPT-5 mini" and ".../gpt-5-mini". Results are sorted alphabetically by
  // label, then the current selection is pinned to the top (Array.sort is
  // stable, so the alphabetical order of the rest is preserved).
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? allOptions.filter(
          (m) =>
            m.label.toLowerCase().includes(q) ||
            m.value.toLowerCase().includes(q),
        )
      : allOptions;
    return [...filtered]
      .sort((a, b) =>
        a.label.localeCompare(b.label, undefined, { sensitivity: "base" }),
      )
      .sort((a, b) => (a.value === value ? -1 : b.value === value ? 1 : 0));
  }, [allOptions, search, value]);

  function setMenuOpen(next: boolean) {
    setOpen(next);
    if (!next) setSearch("");
  }

  function choose(v: string) {
    onChange(v);
    setMenuOpen(false);
  }

  return (
    <Popover modal open={open} onOpenChange={setMenuOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="af-input flex items-center justify-between gap-2 w-full text-left"
          aria-label={ariaLabel}
          aria-haspopup="listbox"
          disabled={disabled}
        >
          <span className="truncate" style={{ color: "var(--ink)" }}>
            {selectedLabel}
          </span>
          <ChevronDownIcon size={14} className="opacity-50 flex-shrink-0" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={MENU_GAP}
        collisionPadding={VIEWPORT_MARGIN}
        className="w-(--radix-popover-trigger-width) max-h-(--radix-popover-content-available-height) gap-0 overflow-hidden rounded-xl p-0 ring-0"
        style={{
          background: "var(--bg-elev)",
          border: "1px solid var(--line)",
          boxShadow: "var(--shadow-pop)",
        }}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
          <input
            ref={inputRef}
            className="flex-1 text-[0.8125rem] outline-none bg-transparent"
            style={{ color: "var(--ink)" }}
            placeholder="Search models…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div role="listbox" className="min-h-0 flex-1 overflow-y-auto py-1">
          {visible.length === 0 ? (
            <div className="px-3 py-2 text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
              No models match.
            </div>
          ) : (
            visible.map((m) => {
              const selected = m.value === value;
              return (
                <button
                  key={m.value}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  className="flex items-center gap-2 w-full px-3 py-2 text-left text-[0.8125rem] hover:bg-[var(--bg-soft)]"
                  style={{
                    color: "var(--ink)",
                    background: selected ? "var(--bg-soft)" : "transparent",
                  }}
                  onClick={() => choose(m.value)}
                >
                  <span className="w-4 flex-shrink-0">
                    {selected && <CheckIcon size={14} style={{ color: "var(--ok)" }} />}
                  </span>
                  <span className="truncate">{m.label}</span>
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
