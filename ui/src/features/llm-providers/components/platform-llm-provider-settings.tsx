"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { formatDate } from "@/shared/date";

import { useOpenRouterConnection } from "../hooks/use-openrouter-connection";
import type { OpenRouterConnection } from "../schemas";
import { LlmProviderConnectionList } from "./llm-provider-connection-list";
import { OpenRouterKeyDialog } from "./openrouter-key-dialog";

const MASKED_KEY_PREFIX = "sk-*******";

export function PlatformLlmProviderSettings() {
  const { connection, isLoading, error, reload, replaceKey, isReplacing, replaceError, resetReplace } =
    useOpenRouterConnection();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogKey, setDialogKey] = useState(0);
  const [saved, setSaved] = useState(false);

  if (isLoading) return <p role="status">Loading LLM provider settings…</p>;
  if (error || !connection)
    return (
      <AppErrorState error={error} title="Could not load LLM provider settings" onRetry={() => void reload()} />
    );

  function openDialog() {
    resetReplace();
    setSaved(false);
    setDialogKey((current) => current + 1);
    setDialogOpen(true);
  }

  async function save(apiKey: string) {
    await replaceKey(apiKey);
    setDialogOpen(false);
    setSaved(true);
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="af-card overflow-hidden" aria-labelledby="openrouter-heading">
        <div className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 id="openrouter-heading" className="m-0 text-sm font-medium">
                OpenRouter
              </h3>
              <KeyStatus connection={connection} />
            </div>
            <button type="button" className="af-btn shrink-0" onClick={openDialog}>
              {connection.hasApiKey ? "Replace key" : "Save a key"}
            </button>
          </div>
          {connection.hasApiKey && connection.envKeyConfigured && (
            <p role="note" className="mb-0 mt-4 text-sm" style={{ color: "var(--ink-3)" }}>
              OPENROUTER_API_KEY is still set in this deployment&apos;s secrets. Agents use the saved key; LiteLLM falls
              back to the secret only while the saved key&apos;s route is unavailable. Delete the secret once every
              environment that shares it has a saved key.
            </p>
          )}
          {saved && (
            <p role="status" className="mb-0 mt-4 text-sm">
              OpenRouter key saved.
            </p>
          )}
        </div>
        <OpenRouterKeyDialog
          key={dialogKey}
          replacing={connection.hasApiKey}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          onSave={save}
          isSaving={isReplacing}
          saveError={replaceError}
        />
      </section>
      <LlmProviderConnectionList />
    </div>
  );
}

function KeyStatus({ connection }: { connection: OpenRouterConnection }) {
  if (!connection.hasApiKey) {
    return (
      <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
        No key saved.{" "}
        {connection.envKeyConfigured
          ? "Agents use OPENROUTER_API_KEY from this deployment's secrets until a key is saved here."
          : "Agents cannot call OpenRouter models until a key is saved."}
      </p>
    );
  }
  const changed = connection.updatedAt ? formatDate(connection.updatedAt) : null;
  return (
    <>
      <p className="mb-0 mt-2 text-sm">
        {MASKED_KEY_PREFIX}
        {connection.apiKeyLast4}
      </p>
      {changed && (
        <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
          {connection.updatedBy ? `Changed by ${connection.updatedBy} on ${changed}` : `Changed on ${changed}`}
        </p>
      )}
    </>
  );
}
