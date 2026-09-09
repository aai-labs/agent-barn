"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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

export function DefaultDeliveryTargetInput({ value, onChange, channels, users }: {
  value: unknown;
  onChange: (value: unknown) => void;
  channels?: BrowseSource;
  users?: BrowseSource;
}) {
  const id = useId();
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  const target = value && typeof value === "object" ? value as Record<string, unknown> : null;
  const kind = String(target?.kind ?? "channel");
  const browse = kind === "user" ? users : channels;
  const update = (next: Record<string, unknown>) => onChange({ ...target, ...next });
  return (
    <FieldSet>
      <FieldLegend>Default delivery target</FieldLegend>
      <Field orientation="horizontal">
        <input id={`${id}-enabled`} type="checkbox" checked={target !== null}
          onChange={(event) => onChange(event.target.checked ? { kind: "channel", recipient: "" } : null)} />
        <FieldLabel htmlFor={`${id}-enabled`}>Send scheduled results through this Connection</FieldLabel>
      </Field>
      <FieldDescription>Only one Connection per Agent may have a default. A disabled Connection cannot deliver scheduled results.</FieldDescription>
      {target && <FieldGroup>
        <Field>
          <FieldLabel htmlFor={`${id}-kind`}>Destination type</FieldLabel>
          <Select value={kind} onValueChange={(next) => update({ kind: next, recipient: "", threadId: null })}>
            <SelectTrigger id={`${id}-kind`}><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup>
              <SelectItem value="channel">Channel or group</SelectItem>
              <SelectItem value="user">Person</SelectItem>
              <SelectItem value="dm">Existing direct message</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor={`${id}-recipient`}>Default channel or recipient</FieldLabel>
          <Input id={`${id}-recipient`} required value={String(target.recipient ?? "")}
            onChange={(event) => update({ recipient: event.target.value })} />
          {browse && kind !== "dm" && <Button type="button" variant="outline" disabled={Boolean(browse.disabledReason)}
            onClick={() => { browse.onOpen?.(); setPicking(true); }}>Browse default destination</Button>}
          {browse?.disabledReason && <FieldDescription>{browse.disabledReason}</FieldDescription>}
        </Field>
        <Field>
          <FieldLabel htmlFor={`${id}-thread`}>Default thread or topic (optional)</FieldLabel>
          <Input id={`${id}-thread`} value={String(target.threadId ?? "")}
            onChange={(event) => update({ threadId: event.target.value || null })} />
        </Field>
        {error && <p role="alert">{error}</p>}
      </FieldGroup>}
      {browse && <DirectoryPickerDialog open={picking} onOpenChange={setPicking} title="Choose one default destination"
        description="Select one destination for scheduled results." searchPlaceholder={`Search ${browse.noun}…`}
        entries={browse.entries} selected={target?.recipient ? [String(target.recipient)] : []}
        isLoading={browse.isLoading} error={browse.error} onConfirm={(ids) => {
          if (ids.length !== 1) { setError("Choose exactly one default destination."); return; }
          setError(""); update({ recipient: ids[0] });
        }} />}
    </FieldSet>
  );
}
