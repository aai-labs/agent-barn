"use client";

import { useState, type ReactNode } from "react";
import { ExternalLink, Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { SettingsSection } from "@/components/settings/settings-section";

import { useAbandonOneDrive, useConnectOneDrive, useDisconnectOneDrive } from "../hooks/use-onedrive-sync-actions";
import { useOneDriveSyncQuery } from "../hooks/use-onedrive-sync-query";
import { OneDriveSitePicker } from "./onedrive-site-picker";

const TITLE = "OneDrive";
const DESCRIPTION = "Where Agent Barn keeps your organization's files in SharePoint.";

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[0.84rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

function ErrorText({ children }: { children: string }) {
  return (
    <p role="alert" className="m-0 text-[0.84rem]" style={{ color: "var(--err)" }}>
      {children}
    </p>
  );
}

export function OneDriveSyncPanel({ canManage }: { canManage: boolean }) {
  const { connection, isLoading, error, refetch } = useOneDriveSyncQuery();
  const { connect, isConnecting } = useConnectOneDrive();
  const { disconnect, isDisconnecting } = useDisconnectOneDrive();
  const { abandon, isAbandoning } = useAbandonOneDrive();
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : fallback);
    }
  }

  function handleDisconnect() {
    // The popup opens synchronously inside this click, before any await, or browsers block it.
    const pending = run(disconnect, "Disconnecting OneDrive failed.");
    setConfirmingDisconnect(false);
    return pending;
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
        <Loader2 size={15} className="animate-spin" /> Loading OneDrive…
      </div>
    );
  }
  if (error || !connection) {
    return <AppErrorState error={error} title="We couldn't load OneDrive" onRetry={() => void refetch()} />;
  }

  return (
    <SettingsSection title={TITLE} description={DESCRIPTION}>
      <div className="flex flex-col gap-3">
        {!connection.available && <Note>OneDrive sync isn&apos;t available on this server.</Note>}

        {connection.available && connection.status === null && (
          <>
            <p className="m-0 text-[0.92rem] font-medium" style={{ color: "var(--ink)" }}>
              Not connected
            </p>
            {canManage ? (
              <>
                <Note>
                  A Microsoft Global Administrator approves Agent Barn for your organization, and the person
                  connecting must be a SharePoint Administrator and a member of the site they pick.
                </Note>
                <button
                  type="button"
                  className="af-btn af-btn-primary w-fit"
                  disabled={isConnecting}
                  onClick={() => void run(connect, "Connecting OneDrive failed.")}
                >
                  {isConnecting ? "Connecting…" : "Connect OneDrive"}
                </button>
              </>
            ) : (
              <Note>An Organization Owner or Admin can connect OneDrive.</Note>
            )}
          </>
        )}

        {connection.available && connection.status === "pending" &&
          (canManage ? (
            <>
              <OneDriveSitePicker />
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
            <Note>A connection was started, but no SharePoint site has been chosen yet.</Note>
          ))}

        {connection.available && connection.status === "active" && connection.folderWebUrl && (
          <>
            <p className="m-0 text-[0.92rem]" style={{ color: "var(--ink)" }}>
              Connected to <span className="font-medium">{connection.siteName}</span>
            </p>
            <a
              className="af-btn af-btn-ghost inline-flex w-fit items-center gap-1.5"
              href={connection.folderWebUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in OneDrive <ExternalLink size={13} aria-hidden />
            </a>
            <Note>
              In OneDrive, choose <span className="font-medium">Add shortcut to My files</span> to keep this folder
              next to your own files.
            </Note>
            {canManage && (
              <button
                type="button"
                className="af-btn af-btn-danger af-btn-sm w-fit"
                disabled={isDisconnecting}
                onClick={() => setConfirmingDisconnect(true)}
              >
                {isDisconnecting ? "Disconnecting…" : "Disconnect"}
              </button>
            )}
          </>
        )}

        {actionError && <ErrorText>{actionError}</ErrorText>}
      </div>
      <ConfirmationDialog
        open={confirmingDisconnect}
        onOpenChange={setConfirmingDisconnect}
        title="Disconnect OneDrive?"
        description="You'll sign in with Microsoft so Agent Barn's access to the site can be removed. The Agent Barn folder and its files stay in SharePoint."
        confirmLabel="Disconnect"
        variant="destructive"
        onConfirm={handleDisconnect}
      />
    </SettingsSection>
  );
}
