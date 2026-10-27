"use client";

import { useState, type ReactNode } from "react";
import { ExternalLink } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";

import {
  useAbandonSyncProvider,
  useConnectSyncProvider,
  useDisconnectSyncProvider,
} from "../hooks/use-sync-provider-actions";
import { FILE_SYNC, LOCATION_PICKER, type SyncProvider } from "../schemas";
import { SyncLocationPicker } from "./sync-location-picker";
import { SyncProviderIcon } from "./sync-provider-icon";

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[0.84rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

/** One provider in the Sync list: what it is or where it syncs, and what this person may do with it. */
export function SyncProviderRow({ provider, canManage }: { provider: SyncProvider; canManage: boolean }) {
  const { connect, isConnecting } = useConnectSyncProvider(provider);
  const { disconnect, isDisconnecting } = useDisconnectSyncProvider(provider);
  const { abandon, isAbandoning } = useAbandonSyncProvider(provider);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);

  const status = provider.connection?.status ?? null;
  const folderUrl = provider.connection?.folderWebUrl ?? null;
  const locationName = provider.connection?.locationName ?? null;
  const noun = provider.locationNoun ?? "location";
  const hasPicker = provider.capabilities.includes(LOCATION_PICKER) && provider.locationNoun !== null;
  const afterDisconnect = provider.capabilities.includes(FILE_SYNC)
    ? "Each Agent's folder inside the Agent Barn folder is deleted once access is removed. The Agent Barn folder stays, and the Agents keep their own files."
    : "The Agent Barn folder and its files stay where they are.";

  if (!provider.available) {
    return (
      <li
        aria-label={provider.displayName}
        className="flex flex-wrap items-center gap-3 px-4 py-3.5"
        style={{ borderColor: "var(--line)" }}
      >
        <SyncProviderIcon providerKey={provider.key} displayName={provider.displayName} />
        <div className="min-w-0 flex-1">
          <div className="text-[0.92rem] font-medium" style={{ color: "var(--ink)" }}>
            {provider.displayName}
          </div>
          <div className="text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
            {provider.displayName} is not configured for the platform.
          </div>
        </div>
      </li>
    );
  }

  async function run(action: () => Promise<unknown>, fallback: string) {
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : fallback);
    }
  }

  function handleDisconnect() {
    const pending = run(disconnect, `Disconnecting ${provider.displayName} failed.`);
    setConfirmingDisconnect(false);
    return pending;
  }

  return (
    <li
      aria-label={provider.displayName}
      className="flex flex-col gap-3 px-4 py-3.5"
      style={{ borderColor: "var(--line)" }}
    >
      <div className="flex flex-wrap items-center gap-3">
        <SyncProviderIcon providerKey={provider.key} displayName={provider.displayName} />
        <div className="min-w-0 flex-1">
          <div className="text-[0.92rem] font-medium" style={{ color: "var(--ink)" }}>
            {provider.displayName}
          </div>
          <div className="text-[0.82rem]" style={{ color: status === "active" ? "var(--ok)" : "var(--ink-3)" }}>
            {status === "active" ? (
              <>
                <span aria-hidden>● </span>
                {locationName ? `Connected to ${locationName}` : "Connected"}
              </>
            ) : status === "pending" ? (
              "Connecting…"
            ) : (
              provider.tagline
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status === null && canManage && (
            <button
              type="button"
              className="af-btn af-btn-primary af-btn-sm"
              disabled={!provider.canConnect || isConnecting}
              onClick={() => void run(connect, `Connecting ${provider.displayName} failed.`)}
            >
              {isConnecting ? "Connecting…" : "Connect"}
            </button>
          )}
          {status === "active" && folderUrl && (
            <a
              className="af-btn af-btn-ghost af-btn-sm inline-flex items-center gap-1.5"
              href={folderUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in {provider.displayName} <ExternalLink size={13} aria-hidden />
            </a>
          )}
          {status === "active" && canManage && (
            <button
              type="button"
              className="af-btn af-btn-danger af-btn-sm"
              disabled={isDisconnecting}
              onClick={() => setConfirmingDisconnect(true)}
            >
              {isDisconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          )}
        </div>
      </div>

      {status === null && canManage && provider.blockedReason && <Note>{provider.blockedReason}</Note>}

      {status === null && canManage && !provider.blockedReason && provider.connectHint && (
        <Note>{provider.connectHint}</Note>
      )}

      {status === null && canManage && provider.approvalUrl && (
        <Note>
          Not approved yet? Send whoever approves apps for your organization the{" "}
          <a
            href={provider.approvalUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--accent-ink)" }}
          >
            approval link
          </a>
          , then connect once they&apos;ve approved.
        </Note>
      )}

      {status === null && !canManage && <Note>An Organization Owner or Admin can connect.</Note>}

      {status === "pending" &&
        (canManage ? (
          <>
            {hasPicker && <SyncLocationPicker provider={provider} noun={noun} />}
            <button
              type="button"
              className="af-btn af-btn-ghost af-btn-sm w-fit"
              disabled={isAbandoning}
              onClick={() => void run(() => abandon(), "Starting over failed.")}
            >
              Start over
            </button>
          </>
        ) : (
          <Note>A connection was started, but no {noun} has been chosen yet.</Note>
        ))}

      {status === "active" && <Note>{provider.folderHint}</Note>}

      {actionError && (
        <p role="alert" className="m-0 text-[0.84rem]" style={{ color: "var(--err)" }}>
          {actionError}
        </p>
      )}

      <ConfirmationDialog
        open={confirmingDisconnect}
        onOpenChange={setConfirmingDisconnect}
        title={`Disconnect ${provider.displayName}?`}
        description={`You'll sign in to ${provider.displayName} again so Agent Barn's access can be removed. ${afterDisconnect}`}
        confirmLabel="Disconnect"
        variant="destructive"
        onConfirm={handleDisconnect}
      />
    </li>
  );
}
