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

const EMPTY_KEY_MESSAGE = "Paste the key from your OpenRouter dashboard.";

export function OpenRouterKeyDialog({
  replacing,
  open,
  onOpenChange,
  onSave,
  isSaving,
  saveError,
}: {
  replacing: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (apiKey: string) => Promise<unknown>;
  isSaving: boolean;
  saveError: unknown;
}) {
  const [apiKey, setApiKey] = useState("");
  const [emptyKey, setEmptyKey] = useState(false);

  async function save() {
    const trimmed = apiKey.trim();
    setEmptyKey(!trimmed);
    if (!trimmed) return;
    try {
      await onSave(trimmed);
    } catch {
      // The refusal is shown beside the key, which stays so it can be corrected.
    }
  }

  const failure = emptyKey ? EMPTY_KEY_MESSAGE : saveError ? getErrorDisplay(saveError).description : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{replacing ? "Replace the OpenRouter key" : "Save an OpenRouter key"}</DialogTitle>
          <DialogDescription>
            OpenRouter checks the key before it is saved. Agents switch to it as soon as it is saved, without a
            restart. Afterwards only its last four characters are shown.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor="openrouter-api-key">
              OpenRouter API key
            </label>
            <input
              id="openrouter-api-key"
              type="password"
              className="af-input w-full"
              value={apiKey}
              maxLength={512}
              onChange={(event) => {
                setApiKey(event.target.value);
                setEmptyKey(false);
              }}
              placeholder="sk-or-…"
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
