"use client";

import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { usePlatformMemorySettings } from "../hooks/use-platform-memory-settings";

export function PlatformMemorySettings() {
  const { settings, models, save } = usePlatformMemorySettings();
  const [draft, setDraft] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  if (settings.isPending) return <div className="af-page">Loading Platform Settings…</div>;
  if (settings.error) return <AppErrorState error={settings.error} title="Could not load Platform Settings" onRetry={() => void settings.refetch()} />;
  const model = draft ?? settings.data?.model ?? "";
  const options = models.data ?? [];
  const label = options.find((item) => item.value === model)?.label ?? model;
  const selectable = options.some((item) => item.value === model);

  async function submit() {
    try {
      await save.mutateAsync(model);
      setDraft(null);
      setSaved(true);
    } catch { /* The error stays beside the model selector. */ }
  }

  return (
    <div className="af-page">
      <h1 className="mb-2 text-2xl font-semibold">Platform Settings</h1>
      <p className="mb-8 text-sm" style={{ color: "var(--ink-3)" }}>Configuration shared across all Organizations.</p>
      <section className="af-card max-w-3xl" aria-label="Agent Memory settings">
        <div className="p-6">
          <h2 className="mb-2 text-lg font-semibold">Agent Memory</h2>
          <p className="mb-6 text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Choose the model used to extract facts, consolidate observations, and reflect on memories for all Agents and Organizations.
            Each Agent keeps its own chat model. Memory processing costs are charged to the Organization using it.
          </p>
          <label className="mb-2 block text-sm font-medium" id="memory-model-label">Memory processing model</label>
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <button type="button" className="af-btn w-full justify-between" role="combobox" aria-controls="memory-model-options" aria-expanded={open}
                aria-labelledby="memory-model-label" disabled={save.isPending || models.isPending || !!models.error}>
                <span className="min-w-0 truncate">{label}</span><ChevronsUpDown className="size-4 shrink-0" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-[min(34rem,90vw)] p-0" align="start">
              <Command>
                <CommandInput placeholder="Search memory models…" />
                <CommandList id="memory-model-options">
                  <CommandEmpty>No supported models found.</CommandEmpty>
                  <CommandGroup>
                    {options.map((option) => <CommandItem key={option.value} value={option.value} keywords={[option.label]}
                      onSelect={() => { setDraft(option.value); setOpen(false); setSaved(false); save.reset(); }}>
                      <Check className={`mr-2 size-4 ${model === option.value ? "opacity-100" : "opacity-0"}`} />
                      {option.label}
                    </CommandItem>)}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
          <p className="mt-3 text-sm" style={{ color: "var(--ink-3)" }}>
            Changes apply to new memory work within five seconds. Work already in progress finishes with its original model.
          </p>
          {models.error && <div className="mt-3" role="alert">The model catalog is unavailable. <button className="af-btn" onClick={() => void models.refetch()}>Retry models</button></div>}
          {save.error && <p className="mt-3 text-sm" role="alert" style={{ color: "var(--danger)" }}>{getErrorDisplay(save.error).description}</p>}
          {saved && <p className="mt-3 text-sm" role="status">Memory processing model saved.</p>}
        </div>
        <div className="flex justify-end gap-2 border-t p-4" style={{ borderColor: "var(--line)" }}>
          <button className="af-btn" disabled={draft === null || save.isPending} onClick={() => { setDraft(null); save.reset(); }}>Cancel</button>
          <button className="af-btn af-btn-primary" disabled={!selectable || model === settings.data?.model || save.isPending || !!models.error}
            onClick={() => void submit()}>{save.isPending ? "Saving…" : "Save"}</button>
        </div>
      </section>
    </div>
  );
}
