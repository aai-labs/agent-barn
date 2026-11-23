"use client";

import { formatDate } from "@/shared/date";

import { OPENROUTER_MASKED_KEY_PREFIX, PROVIDER_SUBTITLES } from "../constants";
import type { LlmProviderConnection } from "../schemas";
import { providerTitle } from "../utils";
import { ProviderInitials } from "./provider-card";

const ENVIRONMENT_VARIABLE = "OPENROUTER_API_KEY";
const IN_USE = { label: "In use", color: "var(--ok)" };
const FALLBACK = { label: "Fallback", color: "var(--warn)" };
const MUTED = { color: "var(--ink-3)" };

export function DeploymentProviderCard({
  connection,
  onReplaceKey,
}: {
  connection: LlmProviderConnection;
  onReplaceKey: () => void;
}) {
  const headingId = `llm-provider-${connection.slug}-deployment-heading`;
  const changed = connection.hasApiKey && connection.updatedAt ? formatDate(connection.updatedAt) : null;
  const status = connection.hasApiKey ? FALLBACK : IN_USE;

  return (
    <section className="af-card p-5" aria-labelledby={headingId}>
      <div className="flex items-start gap-3">
        <ProviderInitials providerType={connection.providerType} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={headingId} className="m-0 text-sm font-medium">
              {providerTitle(connection)}
            </h3>
            <span
              className="rounded-md px-1.5 py-0.5 text-xs font-medium"
              style={{ background: "var(--warn-soft)", color: "var(--warn)" }}
            >
              Environment
            </span>
          </div>
          <p className="mb-0 mt-1 text-sm" style={MUTED}>
            {PROVIDER_SUBTITLES[connection.providerType]}
          </p>
        </div>
      </div>
      <dl className="mb-0 mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        <dt className="font-mono break-all" style={MUTED}>
          {ENVIRONMENT_VARIABLE}
        </dt>
        <dd className="m-0">
          {OPENROUTER_MASKED_KEY_PREFIX}
          {connection.envKeyLast4}
        </dd>
        {connection.hasApiKey && (
          <>
            <dt style={MUTED}>Saved key</dt>
            <dd className="m-0">
              {OPENROUTER_MASKED_KEY_PREFIX}
              {connection.apiKeyLast4}
            </dd>
          </>
        )}
      </dl>
      {changed && (
        <p className="mb-0 mt-1 text-sm" style={MUTED}>
          {connection.updatedBy ? `Changed by ${connection.updatedBy} on ${changed}` : `Changed on ${changed}`}
        </p>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-sm">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ background: status.color }}
          />
          {status.label}
        </span>
        <button type="button" className="af-btn" onClick={onReplaceKey}>
          {connection.hasApiKey ? "Replace key" : "Save a key"}
        </button>
      </div>
    </section>
  );
}
