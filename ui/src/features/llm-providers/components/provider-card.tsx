"use client";

import { formatDate } from "@/shared/date";

import { MASKED_KEY_PREFIX, PROVIDER_TYPE_LABELS } from "../constants";
import type { LlmProviderConnection } from "../schemas";

const OPENROUTER_MASKED_KEY_PREFIX = "sk-*******";
const MUTED = { color: "var(--ink-3)" };

export function ProviderCard({
  connection,
  onReplaceKey,
  onDelete,
}: {
  connection: LlmProviderConnection;
  onReplaceKey: () => void;
  onDelete?: () => void;
}) {
  const headingId = `llm-provider-${connection.slug}-heading`;
  const isOpenRouter = connection.providerType === "openrouter";
  const changed = connection.hasApiKey && connection.updatedAt ? formatDate(connection.updatedAt) : null;

  return (
    <section className="af-card p-5" aria-labelledby={headingId}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="m-0 text-sm font-medium">
            {connection.name}
          </h3>
          {connection.baseUrl && (
            <p className="mb-0 mt-1 text-sm break-all" style={MUTED}>
              {PROVIDER_TYPE_LABELS[connection.providerType]} · {connection.baseUrl}
            </p>
          )}
          {connection.hasApiKey ? (
            <p className="mb-0 mt-2 text-sm">
              {isOpenRouter ? OPENROUTER_MASKED_KEY_PREFIX : MASKED_KEY_PREFIX}
              {connection.apiKeyLast4}
            </p>
          ) : (
            <p className="mb-0 mt-2 text-sm" style={MUTED}>
              No key saved.
              {isOpenRouter &&
                (connection.envKeyConfigured
                  ? " Agents use OPENROUTER_API_KEY from this deployment's secrets until a key is saved here."
                  : " Agents cannot call OpenRouter models until a key is saved.")}
            </p>
          )}
          {changed && (
            <p className="mb-0 mt-1 text-sm" style={MUTED}>
              {connection.updatedBy ? `Changed by ${connection.updatedBy} on ${changed}` : `Changed on ${changed}`}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button type="button" className="af-btn" onClick={onReplaceKey}>
            {connection.hasApiKey ? "Replace key" : "Save a key"}
          </button>
          {onDelete && (
            <button type="button" className="af-btn" onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      </div>
      {isOpenRouter && connection.hasApiKey && connection.envKeyConfigured && (
        <p role="note" className="mb-0 mt-4 text-sm" style={MUTED}>
          OPENROUTER_API_KEY is still set in this deployment&apos;s secrets. Agents use the saved key; LiteLLM falls back
          to the secret only while the saved key&apos;s route is unavailable. Delete the secret once every environment
          that shares it has a saved key.
        </p>
      )}
    </section>
  );
}
