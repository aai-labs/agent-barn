"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { CheckIcon, SearchIcon } from "@/components/icons";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useModels } from "../hooks/use-models";
import type { ModelOption } from "../schemas";

const MENU_GAP = 4;
const VIEWPORT_MARGIN = 8;
const OPENROUTER = "OpenRouter";

type ModelGroup = { connection: string; options: ModelOption[] };

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
  // "GPT-5 mini" and ".../gpt-5-mini", across every connection. Options without a
  // connection (a kept current value) come first; then one group per connection,
  // OpenRouter first and the rest by name, each sorted alphabetically by label.
  const { ungrouped, groups } = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = (q
      ? allOptions.filter(
          (m) =>
            m.label.toLowerCase().includes(q) ||
            m.value.toLowerCase().includes(q),
        )
      : allOptions
    ).sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: "base" }),
    );
    const byConnection = new Map<string, ModelOption[]>();
    for (const option of filtered) {
      if (!option.connection) continue;
      byConnection.set(option.connection, [...(byConnection.get(option.connection) ?? []), option]);
    }
    const ordered: ModelGroup[] = [...byConnection.entries()]
      .map(([connection, options]) => ({ connection, options }))
      .sort((a, b) =>
        a.connection === OPENROUTER
          ? -1
          : b.connection === OPENROUTER
            ? 1
            : a.connection.localeCompare(b.connection, undefined, { sensitivity: "base" }),
      );
    return { ungrouped: filtered.filter((option) => !option.connection), groups: ordered };
  }, [allOptions, search]);

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
          {ungrouped.length === 0 && groups.length === 0 ? (
            <div className="px-3 py-2 text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
              No models match.
            </div>
          ) : (
            <>
              {ungrouped.map((m) => (
                <ModelOptionButton key={m.value} option={m} selected={m.value === value} onChoose={choose} />
              ))}
              {groups.map((group) => (
                <div key={group.connection} role="group" aria-label={group.connection}>
                  <div
                    aria-hidden
                    className="px-3 pt-2 pb-1 text-[0.72rem] font-medium uppercase tracking-wide"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {group.connection}
                  </div>
                  {group.options.map((m) => (
                    <ModelOptionButton key={m.value} option={m} selected={m.value === value} onChoose={choose} />
                  ))}
                </div>
              ))}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ModelOptionButton({
  option,
  selected,
  onChoose,
}: {
  option: ModelOption;
  selected: boolean;
  onChoose: (value: string) => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      className="flex items-center gap-2 w-full px-3 py-2 text-left text-[0.8125rem] hover:bg-[var(--bg-soft)]"
      style={{
        color: "var(--ink)",
        background: selected ? "var(--bg-soft)" : "transparent",
      }}
      onClick={() => onChoose(option.value)}
    >
      <span className="w-4 flex-shrink-0">
        {selected && <CheckIcon size={14} style={{ color: "var(--ok)" }} />}
      </span>
      <span className="truncate">{option.label}</span>
    </button>
  );
}
