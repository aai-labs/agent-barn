"use client";

import { useState, type ReactNode } from "react";
import { Check, ChevronsUpDown, Pencil } from "lucide-react";

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

export interface ModelOption {
  value: string;
  label: string;
}

interface ModelSettingCardProps {
  ariaLabel: string;
  /** Names the field and the combobox. */
  fieldLabel: string;
  /** Prefix for the label and option list element IDs. */
  fieldId: string;
  summaryTestId: string;
  searchPlaceholder: string;
  editHint: ReactNode;
  savedMessage: string;
  /** Read-only facts shown beside the saved model. */
  details: { label: string; value: ReactNode }[];
  currentModel: string;
  availableModels: ModelOption[];
  isLoadingModels: boolean;
  modelsError: unknown;
  reloadModels: () => unknown;
  saveModel: (model: string) => Promise<unknown>;
  isSavingModel: boolean;
  saveError: unknown;
  resetSave: () => void;
}

/** A Platform-wide model choice: a read-only summary with Edit, then a searchable picker with Save and Cancel. */
export function ModelSettingCard({
  ariaLabel,
  fieldLabel,
  fieldId,
  summaryTestId,
  searchPlaceholder,
  editHint,
  savedMessage,
  details,
  currentModel,
  availableModels,
  isLoadingModels,
  modelsError,
  reloadModels,
  saveModel,
  isSavingModel,
  saveError,
  resetSave,
}: ModelSettingCardProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [editing, setEditing] = useState(false);
  const model = draft ?? currentModel;
  const label = availableModels.find((item) => item.value === model)?.label ?? model;
  const selectable = availableModels.some((item) => item.value === model);

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
    <section className="af-card overflow-hidden" aria-label={ariaLabel}>
      <div className="p-5">
        {editing ? (
          <>
            <label className="mb-2 block text-sm font-medium" id={`${fieldId}-label`}>
              {fieldLabel}
            </label>
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="af-btn w-full justify-between"
                  role="combobox"
                  aria-controls={`${fieldId}-options`}
                  aria-expanded={open}
                  aria-labelledby={`${fieldId}-label`}
                  disabled={isSavingModel || isLoadingModels || !!modelsError}
                >
                  <span className="min-w-0 truncate">{label}</span>
                  <ChevronsUpDown className="size-4 shrink-0" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-[min(34rem,90vw)] p-0" align="start">
                <Command>
                  <CommandInput placeholder={searchPlaceholder} />
                  <CommandList id={`${fieldId}-options`}>
                    <CommandEmpty>No supported models found.</CommandEmpty>
                    <CommandGroup>
                      {availableModels.map((option) => (
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
                          <Check className={`mr-2 size-4 ${model === option.value ? "opacity-100" : "opacity-0"}`} />
                          {option.label}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            <p className="mt-3 text-sm" style={{ color: "var(--ink-3)" }}>
              {editHint}
            </p>
          </>
        ) : (
          <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
            <div>
              <dt
                className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                style={{ color: "var(--ink-4)" }}
              >
                {fieldLabel}
              </dt>
              <dd className="m-0 text-[0.9rem]" data-testid={summaryTestId}>
                {label}
              </dd>
              <dd className="mb-0 ml-0 mt-1 break-all font-mono text-xs" style={{ color: "var(--ink-3)" }}>
                {model}
              </dd>
            </div>
            {details.map((detail) => (
              <div key={detail.label}>
                <dt
                  className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
                  style={{ color: "var(--ink-4)" }}
                >
                  {detail.label}
                </dt>
                <dd className="m-0 text-[0.9rem]">{detail.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {!!modelsError && (
          <div className="mt-3" role="alert">
            The model catalog is unavailable.{" "}
            <button className="af-btn" onClick={() => void reloadModels()}>
              Retry models
            </button>
          </div>
        )}
        {!!saveError && (
          <p className="mt-3 text-sm" role="alert" style={{ color: "var(--danger)" }}>
            {getErrorDisplay(saveError).description}
          </p>
        )}
        {saved && (
          <p className="mt-3 text-sm" role="status">
            {savedMessage}
          </p>
        )}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
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
              disabled={!selectable || model === currentModel || isSavingModel || !!modelsError}
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
  );
}
