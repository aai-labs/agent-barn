"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { formatDate } from "@/shared/date";

import { useLlmProviderActions, useLlmProviderConnections } from "../hooks/use-llm-provider-connections";
import type { KeyReplacement, LlmProviderConnection } from "../schemas";
import { LlmProviderConnectionList, type Notice } from "./llm-provider-connection-list";
import { ProviderKeyDialog } from "./provider-key-dialog";

const MASKED_KEY_PREFIX = "sk-*******";

export function PlatformLlmProviderSettings() {
  const { connections, isLoadingConnections, connectionsError, reloadConnections } = useLlmProviderConnections();
  const { replaceKey, isReplacing, replaceError, resetReplace } = useLlmProviderActions();
  const [target, setTarget] = useState<LlmProviderConnection | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogKey, setDialogKey] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);

  if (isLoadingConnections) return <p role="status">Loading LLM provider settings…</p>;
  if (connectionsError || !connections)
    return (
      <AppErrorState
        error={connectionsError}
        title="Could not load LLM provider settings"
        onRetry={() => void reloadConnections()}
      />
    );

  const openRouter = connections.find((connection) => connection.providerType === "openrouter");
  const others = connections.filter((connection) => connection.providerType !== "openrouter");

  function openKeyDialog(connection: LlmProviderConnection) {
    resetReplace();
    setNotice(null);
    setTarget(connection);
    setDialogKey((current) => current + 1);
    setDialogOpen(true);
  }

  async function save(slug: string, replacement: KeyReplacement) {
    const saved = await replaceKey({ slug, ...replacement });
    setDialogOpen(false);
    setNotice({ slug: saved.slug, text: `${saved.name} key saved.` });
  }

  return (
    <div className="flex flex-col gap-4">
      {openRouter && (
        <section className="af-card overflow-hidden" aria-labelledby="openrouter-heading">
          <div className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="openrouter-heading" className="m-0 text-sm font-medium">
                  OpenRouter
                </h3>
                <KeyStatus connection={openRouter} />
              </div>
              <button type="button" className="af-btn shrink-0" onClick={() => openKeyDialog(openRouter)}>
                {openRouter.hasApiKey ? "Replace key" : "Save a key"}
              </button>
            </div>
            {openRouter.hasApiKey && openRouter.envKeyConfigured && (
              <p role="note" className="mb-0 mt-4 text-sm" style={{ color: "var(--ink-3)" }}>
                OPENROUTER_API_KEY is still set in this deployment&apos;s secrets. Agents use the saved key; LiteLLM
                falls back to the secret only while the saved key&apos;s route is unavailable. Delete the secret once
                every environment that shares it has a saved key.
              </p>
            )}
            {notice?.slug === openRouter.slug && (
              <p role="status" className="mb-0 mt-4 text-sm">
                {notice.text}
              </p>
            )}
          </div>
        </section>
      )}
      <LlmProviderConnectionList
        connections={others}
        notice={notice}
        onNotice={setNotice}
        onReplaceKey={openKeyDialog}
      />
      {target && (
        <ProviderKeyDialog
          key={dialogKey}
          connection={target}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          onSave={(replacement) => save(target.slug, replacement)}
          isSaving={isReplacing}
          saveError={replaceError}
        />
      )}
    </div>
  );
}

function KeyStatus({ connection }: { connection: LlmProviderConnection }) {
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
