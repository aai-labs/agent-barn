"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { formatDate } from "@/shared/date";

import {
  BASE_URL_PROVIDER_TYPES,
  KNOWN_PROVIDER_TYPES,
  MASKED_KEY_PREFIX,
  PROVIDER_TYPE_LABELS,
} from "../constants";
import { useLlmProviderConnections } from "../hooks/use-llm-provider-connections";
import type { LlmProviderConnection, NewLlmProviderConnection } from "../schemas";
import { AddLlmProviderDialog } from "./add-llm-provider-dialog";

export function LlmProviderConnectionList() {
  const {
    connections,
    isLoadingConnections,
    connectionsError,
    reloadConnections,
    addConnection,
    isAdding,
    addError,
    resetAdd,
  } = useLlmProviderConnections();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogKey, setDialogKey] = useState(0);
  const [added, setAdded] = useState<string | null>(null);

  const others = connections?.filter((connection) => connection.providerType !== "openrouter") ?? [];
  const connected = new Set(others.map((connection) => connection.providerType));
  const available = [...KNOWN_PROVIDER_TYPES.filter((type) => !connected.has(type)), ...BASE_URL_PROVIDER_TYPES];

  function openDialog() {
    resetAdd();
    setAdded(null);
    setDialogKey((current) => current + 1);
    setDialogOpen(true);
  }

  async function add(connection: NewLlmProviderConnection) {
    const saved = await addConnection(connection);
    setDialogOpen(false);
    setAdded(`${saved.name} added.`);
  }

  return (
    <section className="af-card overflow-hidden" aria-labelledby="other-providers-heading">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <h3 id="other-providers-heading" className="m-0 text-sm font-medium">
            Other providers
          </h3>
          {connections && (
            <button type="button" className="af-btn shrink-0" onClick={openDialog}>
              Add provider
            </button>
          )}
        </div>
        {isLoadingConnections ? (
          <p role="status" className="mb-0 mt-2 text-sm">
            Loading other providers…
          </p>
        ) : connectionsError || !connections ? (
          <AppErrorState
            className="min-h-0 p-0 pt-4"
            error={connectionsError}
            title="Could not load the other LLM providers"
            onRetry={() => void reloadConnections()}
          />
        ) : others.length === 0 ? (
          <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
            No other provider is connected.
          </p>
        ) : (
          <div className="mt-2">
            {others.map((connection) => (
              <ConnectionCard key={connection.slug} connection={connection} />
            ))}
          </div>
        )}
        {added && (
          <p role="status" className="mb-0 mt-4 text-sm">
            {added}
          </p>
        )}
      </div>
      <AddLlmProviderDialog
        key={dialogKey}
        available={available}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onAdd={add}
        isAdding={isAdding}
        addError={addError}
      />
    </section>
  );
}

function ConnectionCard({ connection }: { connection: LlmProviderConnection }) {
  const headingId = `llm-provider-${connection.slug}-heading`;
  const changed = connection.hasApiKey && connection.updatedAt ? formatDate(connection.updatedAt) : null;
  return (
    <section aria-labelledby={headingId} className="border-t py-3 first:border-t-0" style={{ borderColor: "var(--line)" }}>
      <h4 id={headingId} className="m-0 text-sm font-medium">
        {connection.name}
      </h4>
      {connection.baseUrl && (
        <p className="mb-0 mt-1 text-sm break-all" style={{ color: "var(--ink-3)" }}>
          {PROVIDER_TYPE_LABELS[connection.providerType]} · {connection.baseUrl}
        </p>
      )}
      <p className="mb-0 mt-1 text-sm">
        {connection.hasApiKey ? `${MASKED_KEY_PREFIX}${connection.apiKeyLast4}` : "No key saved."}
      </p>
      {changed && (
        <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
          {connection.updatedBy ? `Changed by ${connection.updatedBy} on ${changed}` : `Changed on ${changed}`}
        </p>
      )}
    </section>
  );
}
