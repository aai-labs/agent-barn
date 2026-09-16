"use client";

import { Search, X } from "lucide-react";
import { useId, useState } from "react";

import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CommunicationDirectoryEntry } from "../schemas";
import { DirectoryPickerDialog } from "./directory-picker-dialog";

type BrowseSource = {
  noun: string;
  entries: CommunicationDirectoryEntry[];
  isLoading?: boolean;
  error?: string | null;
  disabledReason?: string | null;
  onOpen?: () => void;
};

function SingleTargetInput({
  label,
  value,
  onChange,
  browse,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  browse?: BrowseSource;
}) {
  const [draft, setDraft] = useState("");
  const [picking, setPicking] = useState(false);
  const commit = (next: string) => {
    const trimmed = next.trim();
    if (trimmed) onChange(trimmed);
    setDraft("");
  };
  const displayName =
    browse?.entries.find((entry) => entry.id === value)?.label ?? value;

  return (
    <div
      className="flex flex-col gap-2 rounded-lg p-2"
      style={{
        border: "1px solid var(--line-strong)",
        background: "var(--bg-elev)",
      }}
    >
      {value && (
        <div className="flex flex-wrap gap-1.5">
          <span
            className="inline-flex max-w-full items-center gap-1 rounded-md py-1 pl-2 pr-1 text-xs"
            style={{
              border: "1px solid var(--line)",
              background: "var(--bg-soft)",
              color: "var(--ink-2)",
            }}
          >
            <span className="truncate">{displayName}</span>
            <button
              type="button"
              aria-label={`Remove ${displayName}`}
              className="grid size-4 flex-shrink-0 cursor-pointer place-items-center rounded transition-colors hover:bg-[var(--bg-sunken)]"
              style={{ color: "var(--ink-4)" }}
              onClick={() => onChange("")}
            >
              <X size={11} strokeWidth={2.5} />
            </button>
          </span>
        </div>
      )}
      {!value && (
        <div className="flex items-center gap-2">
          <input
            className="min-w-0 flex-1 bg-transparent px-1 py-1 text-sm font-normal outline-none"
            style={{ color: "var(--ink)" }}
            aria-label={label}
            value={draft}
            placeholder="Add an ID…"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commit(draft);
              }
            }}
            onBlur={() => commit(draft)}
          />
          {browse && (
            <button
              type="button"
              className="af-btn af-btn-sm flex-shrink-0"
              aria-label={`Browse ${label}`}
              disabled={Boolean(browse.disabledReason)}
              onClick={() => {
                browse.onOpen?.();
                setPicking(true);
              }}
            >
              <Search size={13} /> Browse
            </button>
          )}
        </div>
      )}
      {browse?.disabledReason && (
        <p className="m-0 px-1 text-xs" style={{ color: "var(--ink-4)" }}>
          {browse.disabledReason}
        </p>
      )}
      {browse && (
        <DirectoryPickerDialog
          open={picking}
          onOpenChange={setPicking}
          title={`Select ${browse.noun}`}
          description={`Search the connected directory and pick one destination. Only its ID is saved.`}
          searchPlaceholder={`Search ${browse.noun}…`}
          entries={browse.entries}
          selected={value ? [value] : []}
          isLoading={browse.isLoading}
          error={browse.error}
          multiple={false}
          onConfirm={(ids) => onChange(ids[0] ?? "")}
        />
      )}
    </div>
  );
}

export function DefaultDeliveryTargetInput({
  value,
  onChange,
  channels,
  users,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  channels?: BrowseSource;
  users?: BrowseSource;
}) {
  const id = useId();
  const target =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : null;
  const kind = String(target?.kind ?? "channel");
  const browse = kind === "user" ? users : channels;
  const update = (next: Record<string, unknown>) =>
    onChange({ ...target, ...next });
  return (
    <FieldSet>
      <FieldLegend>Default delivery target</FieldLegend>
      <Field orientation="horizontal">
        <input
          id={`${id}-enabled`}
          type="checkbox"
          checked={target !== null}
          onChange={(event) =>
            onChange(
              event.target.checked ? { kind: "channel", recipient: "" } : null,
            )
          }
        />
        <FieldLabel htmlFor={`${id}-enabled`}>
          Send scheduled results through this Connection
        </FieldLabel>
      </Field>
      <FieldDescription>
        Only one Connection per Agent may have a default. A disabled Connection
        cannot deliver scheduled results.
      </FieldDescription>
      {target && (
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor={`${id}-kind`}>Destination type</FieldLabel>
            <Select
              value={kind}
              onValueChange={(next) => update({ kind: next, recipient: "" })}
            >
              <SelectTrigger id={`${id}-kind`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="channel">Channel or group</SelectItem>
                  <SelectItem value="user">Person</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel>Default channel or recipient</FieldLabel>
            <SingleTargetInput
              label="Default channel or recipient"
              value={String(target.recipient ?? "")}
              onChange={(next) => update({ recipient: next })}
              browse={browse}
            />
          </Field>
        </FieldGroup>
      )}
    </FieldSet>
  );
}
