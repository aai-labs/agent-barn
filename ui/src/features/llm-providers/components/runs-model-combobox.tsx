"use client";

import { useId, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export const OTHER_LABEL = "Other (type prices)";
const OTHER_VALUE = "__other__";
const UNCHOSEN_LABEL = "Choose a model";

export function RunsModelCombobox({
  label,
  models,
  runsModel,
  other,
  onChoose,
}: {
  label: string;
  models: string[];
  runsModel: string | null;
  other: boolean;
  onChoose: (runsModel: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const listId = useId();
  const term = query.trim().toLowerCase();
  const visible = term ? models.filter((model) => model.toLowerCase().includes(term)) : models;

  function choose(model: string | null) {
    onChoose(model);
    setOpen(false);
    setQuery("");
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          aria-controls={listId}
          className="af-input flex w-44 items-center justify-between gap-2"
        >
          <span className="truncate text-left">{other ? OTHER_LABEL : (runsModel ?? UNCHOSEN_LABEL)}</span>
          <ChevronsUpDown size={14} className="shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent id={listId} className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search LiteLLM's Azure models…" value={query} onValueChange={setQuery} />
          <CommandList>
            <CommandGroup>
              {visible.map((model) => (
                <CommandItem key={model} value={model} onSelect={() => choose(model)}>
                  <Check
                    size={14}
                    className={cn("mr-2", !other && runsModel === model ? "opacity-100" : "opacity-0")}
                  />
                  <span className="truncate">{model}</span>
                </CommandItem>
              ))}
              <CommandItem value={OTHER_VALUE} onSelect={() => choose(null)}>
                <Check size={14} className={cn("mr-2", other ? "opacity-100" : "opacity-0")} />
                {OTHER_LABEL}
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
