"use client";

import type { ReactNode } from "react";
import { ExternalLink, Loader2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { SettingsSection } from "@/components/settings/settings-section";

import { useOneDriveSyncQuery } from "../hooks/use-onedrive-sync-query";

const TITLE = "OneDrive";
const DESCRIPTION = "Where Agent Barn keeps your organization's files in SharePoint.";

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-[0.84rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

export function OneDriveSyncPanel({ canManage }: { canManage: boolean }) {
  const { connection, isLoading, error, refetch } = useOneDriveSyncQuery();

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
              <Note>
                A Microsoft Global Administrator approves Agent Barn for your organization, and the person
                connecting must be a SharePoint Administrator and a member of the site they pick.
              </Note>
            ) : (
              <Note>An Organization Owner or Admin can connect OneDrive.</Note>
            )}
          </>
        )}

        {connection.available && connection.status === "pending" && (
          <Note>A connection was started, but no SharePoint site has been chosen yet.</Note>
        )}

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
          </>
        )}
      </div>
    </SettingsSection>
  );
}
