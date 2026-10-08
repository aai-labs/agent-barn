"use client";

import { useState } from "react";
import { Check, ChevronsUpDown, Pencil } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
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
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { usePlatformMemorySettings } from "../hooks/use-platform-memory-settings";

/** The Agent Memory section of the platform settings page. */
export function PlatformMemorySettings() {
  const {
    memorySettings,
    isLoadingSettings,
    settingsError,
    reloadSettings,
    availableModels,
    isLoadingModels,
    modelsError,
    reloadModels,
    saveModel,
    isSavingModel,
    saveError,
    resetSave,
  } = usePlatformMemorySettings();
  const [draft, setDraft] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [editing, setEditing] = useState(false);
  if (isLoadingSettings) return <p className="m-0">Loading Agent Memory settings…</p>;
  if (settingsError)
    return (
      <AppErrorState
        error={settingsError}
        title="Could not load Platform Settings"
        onRetry={() => void reloadSettings()}
      />
    );
  const model = draft ?? memorySettings?.model ?? "";
  const options = availableModels;
  const label = options.find((item) => item.value === model)?.label ?? model;
  const selectable = options.some((item) => item.value === model);

  async function submit() {
    try {
      await saveModel(model);
      setDraft(null);
      setSaved(true);
      setEditing(false);
    } catch {
      /* The error stays beside the model selector. */
    }
  }

  return (
    <>
        <section
          className="af-card overflow-hidden"
          aria-label="Agent Memory settings"
        >
          <div className="p-5">
            {editing ? (
              <>
                <label
                  className="mb-2 block text-sm font-medium"
                  id="memory-model-label"
                >
                  Memory processing model
                </label>
                <Popover open={open} onOpenChange={setOpen}>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      className="af-btn w-full justify-between"
                      role="combobox"
                      aria-controls="memory-model-options"
                      aria-expanded={open}
                      aria-labelledby="memory-model-label"
                      disabled={
                        isSavingModel || isLoadingModels || !!modelsError
                      }
                    >
                      <span className="min-w-0 truncate">{label}</span>
                      <ChevronsUpDown className="size-4 shrink-0" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent
                    className="w-[min(34rem,90vw)] p-0"
                    align="start"
                  >
                    <Command>
                      <CommandInput placeholder="Search memory models…" />
                      <CommandList id="memory-model-options">
                        <CommandEmpty>No supported models found.</CommandEmpty>
                        <CommandGroup>
                          {options.map((option) => (
                            <CommandItem
                              key={option.value}
                              value={option.value}
                              keywords={[option.label]}
                              onSelect={() => {
                                setDraft(option.value);
                                setOpen(false);
                                setSaved(false);
                                resetSave();
                              }}
                            >
                              <Check
                                className={`mr-2 size-4 ${model === option.value ? "opacity-100" : "opacity-0"}`}
                              />
                              {option.label}
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
                <p className="mt-3 text-sm" style={{ color: "var(--ink-3)" }}>
                  Changes apply to new memory work within five seconds. Work
                  already in progress finishes with its original model.
                </p>
              </>
            ) : (
              <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
                <div>
                  <dt
                    className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                    style={{ color: "var(--ink-4)" }}
                  >
                    Memory processing model
                  </dt>
                  <dd
                    className="m-0 text-[0.9rem]"
                    data-testid="saved-memory-model"
                  >
                    {label}
                  </dd>
                  <dd
                    className="mb-0 ml-0 mt-1 break-all font-mono text-xs"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {model}
                  </dd>
                </div>
                <div>
                  <dt
                    className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                    style={{ color: "var(--ink-4)" }}
                  >
                    Applies to
                  </dt>
                  <dd className="m-0 text-[0.9rem]">
                    All Agents and Organizations
                  </dd>
                </div>
                <div>
                  <dt
                    className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                    style={{ color: "var(--ink-4)" }}
                  >
                    Used for
                  </dt>
                  <dd className="m-0 text-[0.9rem]">
                    Fact extraction, observations, and reflection
                  </dd>
                </div>
                <div>
                  <dt
                    className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                    style={{ color: "var(--ink-4)" }}
                  >
                    Costs charged to
                  </dt>
                  <dd className="m-0 text-[0.9rem]">
                    The Organization using memory
                  </dd>
                </div>
              </dl>
            )}
            {modelsError && (
              <div className="mt-3" role="alert">
                The model catalog is unavailable.{" "}
                <button className="af-btn" onClick={() => void reloadModels()}>
                  Retry models
                </button>
              </div>
            )}
            {saveError && (
              <p
                className="mt-3 text-sm"
                role="alert"
                style={{ color: "var(--danger)" }}
              >
                {getErrorDisplay(saveError).description}
              </p>
            )}
            {saved && (
              <p className="mt-3 text-sm" role="status">
                Memory processing model saved.
              </p>
            )}
          </div>
          <footer
            className="flex flex-wrap justify-end gap-2 border-t px-5 py-3"
            style={{ borderColor: "var(--line)" }}
          >
            {editing ? (
              <>
                <button
                  className="af-btn"
                  disabled={isSavingModel}
                  onClick={() => {
                    setDraft(null);
                    setEditing(false);
                    setOpen(false);
                    resetSave();
                  }}
                >
                  Cancel
                </button>
                <button
                  className="af-btn af-btn-primary"
                  disabled={
                    !selectable ||
                    model === memorySettings?.model ||
                    isSavingModel ||
                    !!modelsError
                  }
                  onClick={() => void submit()}
                >
                  {isSavingModel ? "Saving…" : "Save"}
                </button>
              </>
            ) : (
              <button
                className="af-btn"
                onClick={() => {
                  setEditing(true);
                  setSaved(false);
                }}
              >
                <Pencil size={14} /> Edit
              </button>
            )}
          </footer>
        </section>
        <section
          className="af-card mt-5 p-5"
          aria-label="About memory processing"
        >
          <h3 className="m-0 text-[0.95rem] font-semibold">
            About memory processing
          </h3>
          <p
            className="mb-0 mt-2 text-[0.84rem] leading-relaxed"
            style={{ color: "var(--ink-3)" }}
          >
            Each Agent keeps its own chat model. This model processes long-term
            memories across the platform. Changing it preserves saved memories
            and applies to new memory work within five seconds.
          </p>
        </section>
    </>
  );
}
