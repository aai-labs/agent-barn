"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDownIcon } from "lucide-react";

import { CheckIcon, SearchIcon } from "@/components/icons";
import { useModels } from "../hooks/use-models";
import type { ModelOption } from "../schemas";

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
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // The menu is portalled to <body>, so it needs viewport coordinates rather than the
  // offset parent's. Every surface this control sits on — the settings cards, the hire
  // dialog — clips its overflow, and an absolutely positioned menu is cut off by the
  // first such ancestor. Escaping the DOM subtree is the only fix that holds wherever
  // the control is dropped.
  const [menuStyle, setMenuStyle] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
    flipped: boolean;
  } | null>(null);

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

  function close() {
    setOpen(false);
    setSearch("");
    setMenuStyle(null);
  }

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node;
      // The menu lives outside rootRef now, so it has to be excluded explicitly or
      // every click inside it would count as an outside click and close the control.
      if (menuRef.current?.contains(target)) return;
      if (rootRef.current && !rootRef.current.contains(target)) {
        close();
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const MENU_GAP = 4;
  const VIEWPORT_MARGIN = 8;

  const position = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - MENU_GAP - VIEWPORT_MARGIN;
    const above = rect.top - MENU_GAP - VIEWPORT_MARGIN;
    // Flip upward only when that genuinely gives more room, so the menu stays put in
    // the common case instead of jumping around as the page scrolls.
    const flip = below < 200 && above > below;
    const maxHeight = Math.max(140, flip ? above : below);
    setMenuStyle({
      top: flip ? rect.top - MENU_GAP : rect.bottom + MENU_GAP,
      left: rect.left,
      width: rect.width,
      maxHeight,
      flipped: flip,
    });
  }, []);

  // Measuring happens in the open handler, not here, so the menu is positioned before
  // its first paint. This effect only keeps that position current.
  useLayoutEffect(() => {
    if (!open) return;
    // `true` catches scrolls in any ancestor container, not just the window.
    window.addEventListener("scroll", position, true);
    window.addEventListener("resize", position);
    return () => {
      window.removeEventListener("scroll", position, true);
      window.removeEventListener("resize", position);
    };
  }, [open, position]);

  // Focus the search field when opening.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  function choose(v: string) {
    onChange(v);
    close();
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        className="af-input flex items-center justify-between gap-2 w-full text-left"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => {
          if (open) {
            close();
            return;
          }
          position();
          setOpen(true);
        }}
      >
        <span className="truncate" style={{ color: "var(--ink)" }}>
          {selectedLabel}
        </span>
        <ChevronDownIcon size={14} className="opacity-50 flex-shrink-0" />
      </button>

      {open &&
        menuStyle &&
        createPortal(
          <div
            ref={menuRef}
            className="z-50 flex flex-col rounded-xl overflow-hidden"
            style={{
              position: "fixed",
              top: menuStyle.top,
              left: menuStyle.left,
              width: menuStyle.width,
              maxHeight: menuStyle.maxHeight,
              transform: menuStyle.flipped ? "translateY(-100%)" : undefined,
              background: "var(--bg-elev)",
              border: "1px solid var(--line)",
              boxShadow: "var(--shadow-pop)",
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
              onKeyDown={(e) => {
                if (e.key === "Escape") close();
              }}
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
        </div>,
          document.body,
        )}
    </div>
  );
}
