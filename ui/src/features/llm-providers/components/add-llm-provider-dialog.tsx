"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { BASE_URL_HINTS, BASE_URL_PROVIDER_TYPES, PROVIDER_TYPE_LABELS } from "../constants";
import type { NewLlmProviderConnection, ProviderType } from "../schemas";
import { OrganizationAccessFields, useOrganizationAccess } from "./provider-organizations-dialog";

const EMPTY_KEY_MESSAGE = "Paste the provider's API key.";
const LABEL_CLASS = "text-[0.8rem] font-medium";
const HINT_CLASS = "m-0 text-[0.75rem]";

export function AddLlmProviderDialog({
  providerType,
  open,
  onOpenChange,
  onAdd,
  isAdding,
  addError,
}: {
  providerType: ProviderType;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (connection: NewLlmProviderConnection) => Promise<unknown>;
  isAdding: boolean;
  addError: unknown;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const organizationAccess = useOrganizationAccess("all", []);
  const takesBaseUrl = BASE_URL_PROVIDER_TYPES.includes(providerType);

  async function add() {
    const trimmedKey = apiKey.trim();
    if (!trimmedKey) return setProblem(EMPTY_KEY_MESSAGE);
    setProblem(null);
    const access =
      organizationAccess.access === "all"
        ? {}
        : { organizationAccess: organizationAccess.access, organizationIds: organizationAccess.organizationIds };
    const connection: NewLlmProviderConnection = takesBaseUrl
      ? { providerType, name: name.trim(), slug: slug.trim(), baseUrl: baseUrl.trim(), apiKey: trimmedKey, ...access }
      : { providerType, apiKey: trimmedKey, ...access };
    await onAdd(connection).catch(() => undefined);
  }

  const failure = problem ?? (addError ? getErrorDisplay(addError).description : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add {PROVIDER_TYPE_LABELS[providerType]}</DialogTitle>
          <DialogDescription>
            The provider checks the key before it is saved. Afterwards only its last four characters are shown.
            Agents can&apos;t use providers other than OpenRouter yet.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void add();
          }}
        >
          {takesBaseUrl && (
            <>
              <TextField id="llm-provider-name" label="Name" value={name} onChange={setName} maxLength={64} />
              <TextField
                id="llm-provider-slug"
                label="Slug"
                value={slug}
                onChange={setSlug}
                maxLength={32}
                hint="Lowercase letters, digits and hyphens. It can't be changed, and it can't be used again once deleted."
              />
              <TextField
                id="llm-provider-base-url"
                label="Base URL"
                value={baseUrl}
                onChange={setBaseUrl}
                maxLength={2048}
                hint={BASE_URL_HINTS[providerType]}
              />
            </>
          )}
          <div className="flex flex-col gap-1.5">
            <label className={LABEL_CLASS} style={{ color: "var(--ink-2)" }} htmlFor="llm-provider-api-key">
              API key
            </label>
            <input
              id="llm-provider-api-key"
              type="password"
              className="af-input w-full"
              value={apiKey}
              maxLength={512}
              onChange={(event) => {
                setApiKey(event.target.value);
                setProblem(null);
              }}
              autoComplete="new-password"
              spellCheck={false}
              aria-invalid={!!failure}
            />
          </div>
          <OrganizationAccessFields state={organizationAccess} legend="Organizations" showLegend />
          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
              {failure}
            </p>
          )}
          <DialogFooter>
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={isAdding}>
              {isAdding && <Loader2 size={14} className="animate-spin" />} Add provider
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  maxLength,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  maxLength: number;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className={LABEL_CLASS} style={{ color: "var(--ink-2)" }} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="af-input w-full"
        value={value}
        maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p id={`${id}-hint`} className={HINT_CLASS} style={{ color: "var(--ink-3)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}
