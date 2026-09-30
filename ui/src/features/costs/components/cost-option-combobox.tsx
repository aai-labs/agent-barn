"use client";

import { useId, useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import type { CostFilterOption } from "../schemas";

interface CostOptionComboboxProps {
  options: CostFilterOption[];
  value: string | null;
  onChange: (option: CostFilterOption | null) => void;
  placeholder: string;
  emptyLabel: string;
  className?: string;
  width?: string;
  testId?: string;
}

/**
 * Searchable picker over an option list the server already scoped.
 *
 * Filtering happens here rather than server-side: the endpoint returns only
 * values that actually have spend in the window, which is a short list even on
 * the platform surface, and refetching per keystroke would make the control feel
 * slower than the list is long.
 */
export function CostOptionCombobox({
  options,
  value,
  onChange,
  placeholder,
  emptyLabel,
  className = "af-input",
  width = "15rem",
  testId,
}: CostOptionComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // A combobox trigger has to name the list it controls, or a screen reader
  // announces the role without ever pointing at the options.
  const listId = useId();

  const selected = useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value],
  );

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return options;
    return options.filter((option) =>
      option.label.toLowerCase().includes(term),
    );
  }, [options, query]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          data-testid={testId}
          className={cn(className, "flex items-center justify-between gap-2")}
          style={{ width }}
        >
          <span className="truncate text-left">
            {selected ? selected.label : placeholder}
          </span>
          <ChevronsUpDown size={14} className="shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent id={listId} className="p-0" style={{ width }} align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={placeholder}
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>{emptyLabel}</CommandEmpty>
            <CommandGroup>
              <CommandItem
                value="__all__"
                onSelect={() => {
                  onChange(null);
                  setOpen(false);
                  setQuery("");
                }}
              >
                <Check
                  size={14}
                  className={cn("mr-2", value ? "opacity-0" : "opacity-100")}
                />
                {placeholder}
              </CommandItem>
              {visible.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  onSelect={() => {
                    onChange(option);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <Check
                    size={14}
                    className={cn(
                      "mr-2",
                      value === option.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{option.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
