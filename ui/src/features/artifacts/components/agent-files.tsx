"use client";

import { useState, type ReactNode } from "react";
import { CircleAlert, CloudOff, HardDrive, Loader2, Trash2, type LucideIcon } from "lucide-react";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { useLoadMoreOnScroll } from "@/hooks/use-load-more-on-scroll";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { AppErrorState } from "@/components/app-error-state";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useArtifacts, useArtifactStorage } from "../hooks/use-artifacts";
import type { Artifact } from "../schemas";
import { ArtifactCard } from "./artifact-card";

function provenance(file: Artifact) {
  if (file.source === "workflow") return `Workflow run ${file.runId?.slice(0, 8)} · attempt ${file.attemptId?.slice(0, 8) ?? "unknown"}`;
  return file.source === "human" ? "Uploaded by a person" : "Chat";
}

function StorageStateCard({ title, description, icon: Icon, loading = false, failed = false, action }: {
  title: string;
  description: string;
  icon: LucideIcon;
  loading?: boolean;
  failed?: boolean;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--line-strong)] px-6 py-20 text-center" role={loading ? "status" : undefined}>
      <div className={`mb-4 flex size-12 items-center justify-center rounded-2xl ${failed ? "bg-[var(--err-soft)] text-[var(--err)]" : "bg-[var(--bg-soft)] text-[var(--ink-3)]"}`}>
        <Icon aria-hidden="true" className={`size-6 ${loading ? "animate-spin" : ""}`} />
      </div>
      <h4 className="mb-1 text-[0.9375rem] font-medium text-[var(--ink)]">{title}</h4>
      <p className="max-w-sm text-[0.844rem] leading-relaxed text-[var(--ink-3)]">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function AgentFiles({ agentId, runId, stepId, polling = false, canManageFiles = false, fileLabels, showHeading = true }: {
  agentId: string;
  runId?: string;
  stepId?: string;
  polling?: boolean;
  canManageFiles?: boolean;
  fileLabels?: Record<string, string>;
  showHeading?: boolean;
}) {
  const { storage, provision } = useArtifactStorage(agentId);
  const { files, download, deleteFile } = useArtifacts(agentId, runId, stepId, polling);
  const [fileToDelete, setFileToDelete] = useState<Artifact | null>(null);
  const loadMoreRef = useLoadMoreOnScroll({
    hasNextPage: Boolean(files.hasNextPage) && !files.isFetchNextPageError,
    isFetchingNextPage: files.isFetchingNextPage,
    fetchNextPage: () => { void files.fetchNextPage(); },
  });
  const items = files.data?.pages.flatMap(page => page.items) ?? [];
  if (files.error && !files.data) return (
    <AppErrorState error={files.error} title="Files are unavailable" onRetry={() => void files.refetch()} />
  );
  if (!files.data) return <p role="status">Loading files…</p>;
  const label = stepId ? "Step artifacts" : runId ? "Run artifacts" : "Agent artifacts";
  return (
    <section aria-label={label} className="mt-4 space-y-4">
      {showHeading && <h3 className="font-semibold">Artifacts</h3>}
      {storage.isPending && <StorageStateCard icon={Loader2} loading title="Checking artifact storage…" description="Checking whether this Agent is ready to share files." />}
      {storage.error && <AppErrorState error={storage.error} title="Storage status is unavailable" onRetry={() => void storage.refetch()} />}
      {storage.data?.state === "NOT_CONFIGURED" && <StorageStateCard icon={CloudOff} title="Artifact storage is unavailable" description="Storage needs to be configured by an administrator. Text conversations remain available." />}
      {storage.data?.state === "PROVISIONING" && (
        <StorageStateCard icon={Loader2} loading title="Provisioning artifact storage…" description="We’re preparing a private place for this Agent’s files. You can keep chatting while we finish. If setup is taking too long, retry the request."
          action={canManageFiles && <Button variant="outline" disabled={provision.isPending} onClick={() => provision.mutate()}>Retry provisioning</Button>} />
      )}
      {["NOT_PROVISIONED", "FAILED"].includes(storage.data?.state ?? "") && (
        <StorageStateCard
          icon={storage.data?.state === "FAILED" ? CircleAlert : HardDrive}
          failed={storage.data?.state === "FAILED"}
          title={storage.data?.state === "FAILED" ? "Artifact storage provisioning failed" : "Artifact Storage Not Provisioned"}
          description={canManageFiles
            ? storage.data?.state === "FAILED" ? "We couldn’t finish setting up storage. Try again to get this Agent ready to share files." : "Give this Agent a private place to publish and share files."
            : "Ask someone with Agent update access to provision storage."}
          action={canManageFiles && (
            <Button disabled={provision.isPending} onClick={() => provision.mutate()}>
              {provision.isPending ? <><Loader2 aria-hidden="true" className="size-4 animate-spin" />Requesting…</> : storage.data?.state === "FAILED" ? "Retry provisioning" : "Provision"}
            </Button>
          )}
        />
      )}
      {provision.error && <AppErrorState error={provision.error} title="Provisioning could not be requested" onRetry={() => provision.mutate()} />}
      {items.length === 0 && storage.data?.state === "READY" && (
        <p className="text-sm text-[var(--ink-3)]">No published files yet.</p>
      )}
      <ul className="space-y-2">
        {items.map(file => (
          <li key={file.id}>
            <ArtifactCard file={file} detail={fileLabels ? fileLabels[file.id] ?? "Other published file" : provenance(file)}
              onDownload={() => download.mutate(file.id)} disabled={download.isPending}
              downloading={download.isPending && download.variables === file.id}
              onDelete={canManageFiles ? () => { deleteFile.reset(); setFileToDelete(file); } : undefined}
              error={download.variables === file.id ? download.error : undefined} />
          </li>
        ))}
      </ul>
      <ConfirmationDialog
        open={fileToDelete !== null}
        onOpenChange={open => { if (!open) { setFileToDelete(null); deleteFile.reset(); } }}
        title="Delete file?"
        description={<>Delete “{fileToDelete?.filename}” from this Agent’s files? This cannot be undone. Files used by an active run or review cannot be deleted.</>}
        confirmLabel="Delete file"
        pendingLabel="Deleting…"
        variant="destructive"
        icon={<Trash2 aria-hidden="true" className="size-5" />}
        isPending={deleteFile.isPending}
        onConfirm={() => {
          if (fileToDelete) deleteFile.mutate(fileToDelete.id, { onSuccess: () => setFileToDelete(null) });
        }}
      >
        {deleteFile.error && (
          <Alert variant="destructive" className="mt-4" style={{ background: "var(--err-soft)", borderColor: "color-mix(in srgb, var(--err) 30%, transparent)", color: "var(--err)" }}>
            <CircleAlert aria-hidden="true" className="size-4" />
            <AlertTitle>File could not be deleted</AlertTitle>
            <AlertDescription style={{ color: "var(--err)" }}>{getErrorDisplay(deleteFile.error).description}</AlertDescription>
          </Alert>
        )}
      </ConfirmationDialog>
      <div ref={loadMoreRef} aria-hidden="true" />
      {files.isFetchingNextPage && <p role="status">Loading more files…</p>}
      {files.isFetchNextPageError && (
        <AppErrorState error={files.error} title="More files could not be loaded" onRetry={() => void files.fetchNextPage()} />
      )}
      <p className="text-xs text-[var(--ink-3)]">
        Downloads use a fresh link valid for 15 minutes. Anyone with the link can download until it expires.
      </p>
    </section>
  );
}
