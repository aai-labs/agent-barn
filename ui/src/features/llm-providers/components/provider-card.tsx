"use client";

import { useId, type ReactNode } from "react";

import { formatDate } from "@/shared/date";

import {
  BASE_URL_PROVIDER_TYPES,
  MASKED_KEY_PREFIX,
  OPENROUTER_MASKED_KEY_PREFIX,
  PROVIDER_INITIALS,
  PROVIDER_SUBTITLES,
  PROVIDER_TYPE_LABELS,
} from "../constants";
import type { LlmProviderConnection, ProviderType } from "../schemas";
import { providerTitle } from "../utils";

const MUTED = { color: "var(--ink-3)" };
const DASHED = { borderStyle: "dashed" } as const;

export function ProviderInitials({ providerType }: { providerType: ProviderType }) {
  return (
    <div
      aria-hidden="true"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xs font-semibold"
      style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
    >
      {PROVIDER_INITIALS[providerType]}
    </div>
  );
}

function CardShell({
  providerType,
  title,
  subtitle,
  dashed,
  children,
}: {
  providerType: ProviderType;
  title: string;
  subtitle: string;
  dashed?: boolean;
  children: ReactNode;
}) {
  const headingId = useId();

  return (
    <section className="af-card flex h-full flex-col p-5" style={dashed ? DASHED : undefined} aria-labelledby={headingId}>
      <div className="flex items-start gap-3">
        <ProviderInitials providerType={providerType} />
        <div className="min-w-0">
          <h3 id={headingId} className="m-0 text-sm font-medium break-words">
            {title}
          </h3>
          <p className="mb-0 mt-1 text-sm break-all" style={MUTED}>
            {subtitle}
          </p>
        </div>
      </div>
      {children}
    </section>
  );
}

function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <p className="mb-0 mt-4 flex items-center gap-2 text-sm">
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ background: connected ? "var(--ok)" : "var(--ink-4)" }}
      />
      {connected ? "Connected" : "Not connected"}
    </p>
  );
}

export function connectionSubtitle(connection: LlmProviderConnection): string {
  return BASE_URL_PROVIDER_TYPES.includes(connection.providerType)
    ? `${PROVIDER_TYPE_LABELS[connection.providerType]} · ${connection.baseUrl}`
    : PROVIDER_SUBTITLES[connection.providerType];
}

export function ProviderCard({
  connection,
  onReplaceKey,
  onManage,
}: {
  connection: LlmProviderConnection;
  onReplaceKey?: () => void;
  onManage?: () => void;
}) {
  const isOpenRouter = connection.providerType === "openrouter";
  const saved = connection.hasApiKey && connection.updatedAt ? formatDate(connection.updatedAt) : null;

  return (
    <CardShell
      providerType={connection.providerType}
      title={providerTitle(connection)}
      subtitle={connectionSubtitle(connection)}
    >
      <ConnectionStatus connected={connection.hasApiKey} />
      {connection.hasApiKey && (
        <p className="mb-0 mt-1 text-sm">
          {isOpenRouter ? OPENROUTER_MASKED_KEY_PREFIX : MASKED_KEY_PREFIX}
          {connection.apiKeyLast4}
        </p>
      )}
      {saved && (
        <p className="mb-0 mt-1 text-sm" style={MUTED}>
          Saved {saved}
        </p>
      )}
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        {onManage && (
          <button type="button" className="af-btn" onClick={onManage}>
            Manage
          </button>
        )}
        {onReplaceKey && (
          <button type="button" className="af-btn" onClick={onReplaceKey}>
            {connection.hasApiKey ? "Replace key" : "Save a key"}
          </button>
        )}
      </div>
    </CardShell>
  );
}

export function AddProviderCard({
  providerType,
  actionLabel,
  showStatus,
  dashed,
  onAdd,
}: {
  providerType: ProviderType;
  actionLabel: string;
  showStatus?: boolean;
  dashed?: boolean;
  onAdd: () => void;
}) {
  return (
    <CardShell
      providerType={providerType}
      title={PROVIDER_TYPE_LABELS[providerType]}
      subtitle={PROVIDER_SUBTITLES[providerType]}
      dashed={dashed}
    >
      {showStatus && <ConnectionStatus connected={false} />}
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        <button type="button" className="af-btn" onClick={onAdd}>
          {actionLabel}
        </button>
      </div>
    </CardShell>
  );
}
