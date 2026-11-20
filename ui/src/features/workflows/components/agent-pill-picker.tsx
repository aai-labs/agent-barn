"use client";

import { Check, Plus } from "lucide-react";
import { useState } from "react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";

import { onRadioGroupKeyDown } from "../utils";

export type AgentChoice = { id: string; name: string };

/** Agent pills shown before the rest collapse into a searchable "+N more". */
const VISIBLE_AGENTS = 4;

const pill = (selected: boolean) =>
  `inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors disabled:opacity-50 ${
    selected
      ? "border-[var(--ink)] bg-[var(--ink)] text-[var(--bg)]"
      : "border-[var(--line-strong)] bg-[var(--bg-elev)] hover:bg-[var(--bg-soft)]"
  }`;

/**
 * One Agent chosen from pills: the first four, plus the chosen one when it is past
 * them, with the rest behind a searchable "+N more". `noneLabel` adds a first pill
 * that clears the choice.
 */
export function AgentPillPicker({
  labelledBy,
  agents,
  value,
  onChange,
  noneLabel,
  disabled = false,
}: {
  /** Id of the visible heading that names the radio group. */
  labelledBy: string;
  agents: AgentChoice[];
  value: string | null;
  onChange: (agentId: string | null) => void;
  noneLabel?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const first = agents.slice(0, VISIBLE_AGENTS);
  const chosen = agents.find((agent) => agent.id === value);
  const shown = chosen && !first.includes(chosen) ? [...first, chosen] : first;
  const hidden = agents.length - shown.length;
  // One tab stop, as for native radios: the checked pill, else the first.
  const checked = (noneLabel && value === null) || shown.some((agent) => agent.id === value);
  const tabIndex = (selected: boolean, first: boolean) =>
    selected || (!checked && first) ? 0 : -1;
  return (
    <div className="flex flex-wrap gap-2">
      <div
        role="radiogroup"
        aria-labelledby={labelledBy}
        className="flex flex-wrap gap-2"
        onKeyDown={onRadioGroupKeyDown}
      >
        {noneLabel && (
          <button
            type="button"
            role="radio"
            aria-checked={value === null}
            tabIndex={tabIndex(value === null, true)}
            disabled={disabled}
            className={pill(value === null)}
            onClick={() => onChange(null)}
          >
            {noneLabel}
          </button>
        )}
        {shown.map((agent, index) => (
          <button
            key={agent.id}
            type="button"
            role="radio"
            aria-checked={value === agent.id}
            tabIndex={tabIndex(value === agent.id, !noneLabel && index === 0)}
            disabled={disabled}
            className={`${pill(value === agent.id)} pl-1.5`}
            onClick={() => onChange(agent.id)}
          >
            <span aria-hidden="true">
              <AgentAvatar agent={agent} size="xs" />
            </span>
            {agent.name}
          </button>
        ))}
      </div>
      {hidden > 0 && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              disabled={disabled}
              className={pill(false)}
              aria-label={`Choose from all ${agents.length} agents`}
            >
              <Plus size={14} aria-hidden="true" /> {hidden} more
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-72 p-0" align="start">
            <Command>
              <CommandInput placeholder="Search agents…" />
              <CommandList>
                <CommandEmpty>No agents found.</CommandEmpty>
                <CommandGroup>
                  {agents.map((agent) => (
                    <CommandItem
                      key={agent.id}
                      value={`${agent.name} ${agent.id}`}
                      onSelect={() => {
                        onChange(agent.id);
                        setOpen(false);
                      }}
                    >
                      <AgentAvatar agent={agent} size="xs" />
                      <span className="truncate">{agent.name}</span>
                      <Check
                        aria-hidden="true"
                        className={`ml-auto ${agent.id === value ? "opacity-100" : "opacity-0"}`}
                      />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
