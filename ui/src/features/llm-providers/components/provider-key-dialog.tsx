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

import { BASE_URL_HINTS } from "../constants";
import type { KeyReplacement, LlmProviderConnection } from "../schemas";
import { providerTitle } from "../utils";

const OPENROUTER_EMPTY_KEY_MESSAGE = "Paste the key from your OpenRouter dashboard.";
const EMPTY_KEY_MESSAGE = "Paste the provider's API key.";
const LABEL_CLASS = "text-[0.8rem] font-medium";

export function ProviderKeyDialog({
  connection,
  open,
  onOpenChange,
  onSave,
  isSaving,
  saveError,
}: {
  connection: LlmProviderConnection;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (replacement: KeyReplacement) => Promise<unknown>;
  isSaving: boolean;
  saveError: unknown;
}) {
  const isOpenRouter = connection.providerType === "openrouter";
  const storedBaseUrl = connection.baseUrl;
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(storedBaseUrl ?? "");
  const [emptyKey, setEmptyKey] = useState(false);

  async function save() {
    const trimmedKey = apiKey.trim();
    setEmptyKey(!trimmedKey);
    if (!trimmedKey) return;
    const trimmedBaseUrl = baseUrl.trim();
    const replacement =
      storedBaseUrl !== null && trimmedBaseUrl !== storedBaseUrl
        ? { apiKey: trimmedKey, baseUrl: trimmedBaseUrl }
        : { apiKey: trimmedKey };
    await onSave(replacement).catch(() => undefined);
  }

  const failure = emptyKey
    ? isOpenRouter
      ? OPENROUTER_EMPTY_KEY_MESSAGE
      : EMPTY_KEY_MESSAGE
    : saveError
      ? getErrorDisplay(saveError).description
      : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {connection.hasApiKey
              ? `Replace the ${providerTitle(connection)} key`
              : `Save a key for ${providerTitle(connection)}`}
          </DialogTitle>
          <DialogDescription>
            {isOpenRouter
              ? "OpenRouter checks the key before it is saved. Agents switch to it as soon as it is saved, without a restart. Afterwards only its last four characters are shown."
              : "The provider checks the key before it is saved. Afterwards only its last four characters are shown."}
            {storedBaseUrl !== null && " A new base URL is checked with the key; leave it as it is to keep it."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {storedBaseUrl !== null && (
            <div className="flex flex-col gap-1.5">
              <label className={LABEL_CLASS} style={{ color: "var(--ink-2)" }} htmlFor="provider-key-base-url">
                Base URL
              </label>
              <input
                id="provider-key-base-url"
                className="af-input w-full"
                value={baseUrl}
                maxLength={2048}
                onChange={(event) => setBaseUrl(event.target.value)}
                spellCheck={false}
                aria-describedby="provider-key-base-url-hint"
              />
              <p id="provider-key-base-url-hint" className="m-0 text-[0.75rem]" style={{ color: "var(--ink-3)" }}>
                {BASE_URL_HINTS[connection.providerType]}
              </p>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <label className={LABEL_CLASS} style={{ color: "var(--ink-2)" }} htmlFor="provider-key-api-key">
              {providerTitle(connection)} API key
            </label>
            <input
              id="provider-key-api-key"
              type="password"
              className="af-input w-full"
              value={apiKey}
              maxLength={512}
              onChange={(event) => {
                setApiKey(event.target.value);
                setEmptyKey(false);
              }}
              placeholder={isOpenRouter ? "sk-or-…" : undefined}
              autoComplete="new-password"
              spellCheck={false}
              aria-invalid={!!failure}
            />
          </div>
          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
              {failure}
            </p>
          )}
          <DialogFooter>
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={isSaving}>
              {isSaving && <Loader2 size={14} className="animate-spin" />} Save key
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
