"use client";

import { useEffect, useState } from "react";
import { useDebouncedValue } from "@tanstack/react-pacer";

import { SearchIcon } from "@/components/icons";

interface SearchInputProps {
  /** Called with the debounced value whenever the (debounced) query changes. */
  onSearch: (value: string) => void;
  placeholder?: string;
  /** Debounce delay in ms. Default 300. */
  debounceMs?: number;
  ariaLabel?: string;
  /** Applied to the wrapper (e.g. width utilities). */
  className?: string;
  initialValue?: string;
}

/**
 * Shared debounced search input. Owns its own input state + debounce and reports only
 * the debounced value, so callers just do `<SearchInput onSearch={setQuery} />` and use
 * `query` directly in their data hook — no per-page debounce boilerplate.
 */
export function SearchInput({
  onSearch,
  placeholder = "Search",
  debounceMs = 300,
  ariaLabel,
  className,
  initialValue = "",
}: SearchInputProps) {
  const [value, setValue] = useState(initialValue);
  const [debounced] = useDebouncedValue(value, { wait: debounceMs });

  // Report the debounced value. Callers pass a stable setter (e.g. a useState
  // setter), so this only fires when the debounced query actually changes.
  useEffect(() => {
    onSearch(debounced);
  }, [debounced, onSearch]);

  return (
    <div className={`relative ${className ?? ""}`}>
      <SearchIcon
        size={14}
        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
        style={{ color: "var(--ink-4)" }}
      />
      <input
        type="text"
        className="af-input w-full"
        // Inline padding-left beats af-input's unlayered `padding` shorthand, so the
        // text clears the icon (a Tailwind `pl-8` utility gets overridden by the class).
        style={{ paddingLeft: "34px" }}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel ?? placeholder}
      />
    </div>
  );
}
