"use client";

import { useState } from "react";
import { CircleAlert, Loader2 } from "lucide-react";

import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { CommunicationDirectoryEntry } from "../schemas";

/** Searchable multi-select over a provider directory (channels, users, roles, servers).
 * The caller stores raw platform IDs, so this only ever hands back `entry.id` values —
 * names are a browsing aid, never what gets saved. */
export function DirectoryPickerDialog({
  open,
  onOpenChange,
  title,
  description,
  searchPlaceholder = "Search…",
  entries,
  selected,
  isLoading = false,
  error = null,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  searchPlaceholder?: string;
  entries: CommunicationDirectoryEntry[];
  selected: string[];
  isLoading?: boolean;
  error?: string | null;
  onConfirm: (ids: string[]) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-xl gap-0 overflow-hidden rounded-2xl p-0 sm:rounded-2xl"
        style={{ background: "var(--bg-elev)", borderColor: "var(--line)", boxShadow: "var(--shadow-pop)" }}
      >
        <DirectoryPickerBody
          title={title}
          description={description}
          searchPlaceholder={searchPlaceholder}
          entries={entries}
          selected={selected}
          isLoading={isLoading}
          error={error}
          onCancel={() => onOpenChange(false)}
          onConfirm={(ids) => {
            onConfirm(ids);
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

function DirectoryPickerBody({
  title,
  description,
  searchPlaceholder,
  entries,
  selected,
  isLoading,
  error,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  searchPlaceholder: string;
  entries: CommunicationDirectoryEntry[];
  selected: string[];
  isLoading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (ids: string[]) => void;
}) {
  const [draft, setDraft] = useState<string[]>(selected);
  const toggle = (id: string) =>
    setDraft((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));

  return (
    <>
      <div className="px-6 pt-6 pb-5">
        <DialogHeader className="gap-1.5">
          <DialogTitle className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            {title}
          </DialogTitle>
          <DialogDescription className="text-[13.5px] leading-[1.6]" style={{ color: "var(--ink-3)" }}>
            {description}
          </DialogDescription>
        </DialogHeader>
      </div>

      <div className="px-6 pb-5">
        <div className="overflow-hidden rounded-xl" style={{ border: "1px solid var(--line)" }}>
          <Command loop className="gap-0 rounded-none! bg-transparent p-0">
            <div className="p-2.5">
              <CommandInput placeholder={searchPlaceholder} aria-label={searchPlaceholder} />
            </div>
            <CommandSeparator />
            <CommandList className="max-h-[19rem] p-2">
              {isLoading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm" style={{ color: "var(--ink-3)" }}>
                  <Loader2 size={15} className="animate-spin" /> Loading…
                </div>
              ) : error ? (
                <div className="flex items-start gap-2 px-2 py-10 text-sm" style={{ color: "var(--err)" }}>
                  <CircleAlert size={15} className="mt-0.5 flex-shrink-0" /> {error}
                </div>
              ) : (
                <>
                  <CommandEmpty className="py-10" style={{ color: "var(--ink-3)" }}>
                    No matches.
                  </CommandEmpty>
                  {entries.map((entry) => (
                    <CommandItem
                      key={entry.id}
                      className="gap-3 px-3 py-2.5"
                      value={`${entry.label} ${entry.detail ?? ""} ${entry.id}`}
                      data-checked={draft.includes(entry.id)}
                      onSelect={() => toggle(entry.id)}
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {entry.label}
                        {entry.detail && (
                          <span className="ml-1.5" style={{ color: "var(--ink-4)" }}>
                            {entry.detail}
                          </span>
                        )}
                      </span>
                      <span className="flex-shrink-0 font-mono text-xs" style={{ color: "var(--ink-4)" }}>
                        {entry.id}
                      </span>
                    </CommandItem>
                  ))}
                </>
              )}
            </CommandList>
          </Command>
        </div>
      </div>

      <DialogFooter
        className="mt-0 items-center border-t px-6 py-4 sm:justify-between"
        style={{ borderColor: "var(--line)" }}
      >
        <span className="text-xs" style={{ color: "var(--ink-4)" }}>
          {draft.length} selected
        </span>
        <div className="flex justify-end gap-2">
          <button type="button" className="af-btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="af-btn af-btn-primary" onClick={() => onConfirm(draft)}>
            OK
          </button>
        </div>
      </DialogFooter>
    </>
  );
}
