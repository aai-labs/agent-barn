"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RotateCcw, Trash2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate } from "@/shared/date";
import { toastError } from "@/shared/toast";

import {
  useApplyRecordedConfiguration,
  useCreateRestorePoint,
  useDeleteRestorePoint,
  useRestoreRestorePoint,
} from "../hooks/use-restore-point-actions";
import { isRestorePointBusy, useRestorePoints } from "../hooks/use-restore-points";
import type { Agent, AgentConfigurationVersion, RestorePoint } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";
import { RestorePointConfigDiff } from "./restore-point-config-diff";
import { RestorePointRestoreDialog } from "./restore-point-restore-dialog";
import {
  RESTORE_POINT_ORIGIN_BADGE,
  RESTORE_POINT_STATUS_LABEL,
  formatArchiveSize,
  nameSkillsInMessage,
  restorePointLabel,
  restorePointTime,
  scheduleIntervalText,
} from "./restore-point-utils";

function StatusPill({ restorePoint }: { restorePoint: RestorePoint }) {
  const busy = isRestorePointBusy(restorePoint);
  const failed = restorePoint.status === "FAILED";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.72rem] font-medium"
      style={{
        background: failed ? "var(--err-soft)" : "var(--bg-soft)",
        border: `1px solid ${failed ? "color-mix(in srgb, var(--err) 35%, var(--line))" : "var(--line)"}`,
        color: failed ? "var(--err)" : "var(--ink-3)",
      }}
    >
      {busy && <Loader2 size={11} className="animate-spin" aria-hidden />}
      {RESTORE_POINT_STATUS_LABEL[restorePoint.status]}
    </span>
  );
}

function RestoreAction({
  reason,
  onClick,
}: {
  reason: string | null;
  onClick: () => void;
}) {
  const button = (
    <button
      type="button"
      className="af-btn af-btn-sm"
      disabled={reason !== null}
      onClick={onClick}
    >
      <RotateCcw size={14} /> Restore
    </button>
  );

  if (!reason) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} data-testid="restore-action">
          {button}
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}

export function AgentRestorePointsSettings({
  agent,
  active,
  canManage,
  canEditConfiguration,
}: {
  agent: Agent;
  active: AgentConfigurationVersion;
  canManage: boolean;
  canEditConfiguration: boolean;
}) {
  const {
    restorePoints,
    cap,
    manualCount,
    scheduledCap,
    scheduleIntervalMinutes,
    hasCapacityData,
    hasMore,
    loadMore,
    isLoadingMore,
    isLoading,
    error,
    refetch,
  } = useRestorePoints(agent.id);
  const createRestorePoint = useCreateRestorePoint(agent.id);
  const deleteRestorePoint = useDeleteRestorePoint(agent.id);
  const applyConfiguration = useApplyRecordedConfiguration(agent.id);
  const [label, setLabel] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<RestorePoint | null>(null);
  const [backupIdsWhenOpened, setBackupIdsWhenOpened] = useState<string[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<RestorePoint | null>(null);
  const restoreWithoutBackup = useRestoreRestorePoint(agent.id);
  const [startedRestore, setStartedRestore] = useState<{
    restorePointId: string;
    reapplyConfiguration: boolean;
    knownBackupIds: string[];
  } | null>(null);

  const isRunning = agent.status === "RUNNING";
  // A scheduled snapshot in progress blocks nothing: the server stops it for a capture or a restore.
  // Nor does a restore point being deleted, which never touches the Agent's own volume.
  const hasWorkInFlight = restorePoints.some(
    (item) => isRestorePointBusy(item) && item.origin !== "SCHEDULED" && item.status !== "DELETING",
  );
  const scheduledSnapshots = restorePoints.filter((item) => item.origin === "SCHEDULED");
  const otherRestorePoints = restorePoints.filter((item) => item.origin !== "SCHEDULED");
  const atCap = cap > 0 && manualCount >= cap;

  // Stated up front rather than discovered through a 409.
  function restoreBlockedReason(restorePoint: RestorePoint): string | null {
    if (isRunning) return "Stop the Agent before restoring a restore point.";
    if (hasWorkInFlight) return "A capture or restore is already running for this Agent.";
    if (restorePoint.status !== "READY") return "Only a ready restore point can be restored.";
    return null;
  }

  function captureBlockedBecause(): string | null {
    // Until a page arrives, cap 0 and an empty list read like room to spare.
    if (!hasCapacityData) {
      return error
        ? "This Agent's restore points could not be loaded, so its remaining capacity is unknown."
        : "Checking this Agent's restore points…";
    }
    if (isRunning) return "Stop the Agent before capturing a restore point.";
    if (hasWorkInFlight) return "A capture or restore is already running for this Agent.";
    if (atCap) {
      return `All ${cap} captures are used. Delete one before capturing another.`;
    }
    return null;
  }

  const captureBlockedReason = captureBlockedBecause();

  // A failed backup leaves its target READY again. Backups that already existed when this restore
  // started are ignored, so an older failure is never taken for this one.
  const startedTarget = restorePoints.find((item) => item.id === startedRestore?.restorePointId);
  const failedBackup =
    startedRestore && startedTarget?.status === "READY" && !hasWorkInFlight
      ? restorePoints.find(
          (item) =>
            item.origin === "PRE_RESTORE" &&
            item.status === "FAILED" &&
            !startedRestore.knownBackupIds.includes(item.id),
        )
      : undefined;

  async function restoreWithoutBackupSnapshot() {
    if (!startedRestore) return;
    try {
      await restoreWithoutBackup.mutateAsync({
        restorePointId: startedRestore.restorePointId,
        reapplyConfiguration: startedRestore.reapplyConfiguration,
        skipBackup: true,
      });
      setStartedRestore(null);
    } catch (caught) {
      toastError(caught);
    }
  }

  async function capture() {
    try {
      await createRestorePoint.mutateAsync(label);
      setLabel("");
    } catch (caught) {
      toastError(caught);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteRestorePoint.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (caught) {
      toastError(caught);
    }
  }

  function renderRow(restorePoint: RestorePoint) {
    const isExpanded = expandedId === restorePoint.id;
    const originBadge = RESTORE_POINT_ORIGIN_BADGE[restorePoint.origin];
    const timestamp = restorePointTime(restorePoint);
    return (
      <div
        key={restorePoint.id}
        className="rounded-xl p-3"
        style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
        data-testid="restore-point-row"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[0.88rem] font-medium" style={{ color: "var(--ink)" }}>
                {restorePointLabel(restorePoint)}
              </span>
              {originBadge && (
                <span
                  className="rounded-full px-2 py-0.5 text-[0.7rem] font-medium"
                  style={{
                    background: "var(--accent-soft)",
                    color: "var(--accent-ink)",
                  }}
                >
                  {originBadge}
                </span>
              )}
              <StatusPill restorePoint={restorePoint} />
            </div>
            <div className="mt-1 text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
              {formatDate(timestamp.value)}
              {!timestamp.isCaptureTime && " (requested)"}
              {" · "}
              {formatArchiveSize(restorePoint.archiveBytes)}
              {restorePoint.fileCount !== null &&
                ` · ${restorePoint.fileCount} ${restorePoint.fileCount === 1 ? "file" : "files"}`}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="af-btn af-btn-sm"
              aria-expanded={isExpanded}
              onClick={() => setExpandedId(isExpanded ? null : restorePoint.id)}
            >
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Configuration
            </button>
            {canManage && (
              <>
                <RestoreAction
                  reason={restoreBlockedReason(restorePoint)}
                  onClick={() => {
                    setBackupIdsWhenOpened(
                      restorePoints.filter((item) => item.origin === "PRE_RESTORE").map((item) => item.id),
                    );
                    setRestoreTarget(restorePoint);
                  }}
                />
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  style={{ color: "var(--err)" }}
                  disabled={isRestorePointBusy(restorePoint)}
                  aria-label={`Delete ${restorePointLabel(restorePoint)}`}
                  onClick={() => setDeleteTarget(restorePoint)}
                >
                  <Trash2 size={14} />
                </button>
              </>
            )}
          </div>
        </div>

        {restorePoint.reapplyConfiguration && (
          <p className="mb-0 mt-2 text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
            The recorded configuration will be re-applied once the files are back.
          </p>
        )}

        {restorePoint.configurationError && (
          <div className="mt-2 text-[0.78rem]" role="alert">
            <p className="mb-0" style={{ color: "var(--err)" }}>
              The recorded configuration was not re-applied: {nameSkillsInMessage(restorePoint.configurationError, restorePoint.configManifest.skills)}
            </p>
            {canManage && canEditConfiguration && (
              <button
                type="button"
                className="af-btn af-btn-sm mt-1.5"
                disabled={applyConfiguration.isPending || isRunning}
                onClick={() => {
                  applyConfiguration.mutateAsync(restorePoint.id).catch(toastError);
                }}
              >
                Re-apply configuration
              </button>
            )}
          </div>
        )}

        {restorePoint.failureReason &&
          (restorePoint.status === "FAILED" || restorePoint.status === "READY") && (
            <p
              className="mb-0 mt-2 text-[0.78rem]"
              style={{ color: "var(--err)" }}
              role="alert"
            >
              {/* A READY row keeps a reason only when a restore from it, run without a
                  backup, failed: the Agent's files may not be what this point holds. */}
              {restorePoint.status === "READY"
                ? `The last restore from this point did not finish: ${restorePoint.failureReason}`
                : restorePoint.failureReason}
            </p>
          )}

        {isExpanded && (
          <RestorePointConfigDiff
            manifest={restorePoint.configManifest}
            agent={agent}
            active={active}
          />
        )}
      </div>
    );
  }

  const captureButton = (
    <button
      type="button"
      className="af-btn af-btn-primary"
      disabled={captureBlockedReason !== null || createRestorePoint.isPending}
      onClick={() => void capture()}
    >
      {createRestorePoint.isPending ? "Capturing…" : "Capture restore point"}
    </button>
  );

  return (
    <>
      <AgentConfigurationSection
        title="Restore points"
        description="Capture the Agent's working files before a risky change, and roll back to them if it goes wrong."
      >
        {hasCapacityData && (
          <div className="mb-6" data-testid="scheduled-snapshots">
            <h3 className="m-0 text-[0.88rem] font-semibold" style={{ color: "var(--ink)" }}>
              Scheduled snapshots
            </h3>
            <p
              className="mb-3 mt-1 text-[0.8rem]"
              style={{ color: "var(--ink-3)" }}
              data-testid="restore-point-schedule"
            >
              {scheduleIntervalMinutes > 0
                ? `A snapshot is taken every ${scheduleIntervalText(scheduleIntervalMinutes)} while the Agent runs, and the newest ${scheduledCap} are kept. To undo a change, restore the snapshot taken just before it.`
                : "Scheduled snapshots are turned off."}
            </p>
            {scheduledSnapshots.length > 0 ? (
              <div className="flex flex-col gap-2">{scheduledSnapshots.map(renderRow)}</div>
            ) : (
              scheduleIntervalMinutes > 0 && (
                <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
                  No scheduled snapshot yet. The first is taken while the Agent runs.
                </p>
              )
            )}
          </div>
        )}

        {hasCapacityData && (
          <>
            <h3 className="m-0 text-[0.88rem] font-semibold" style={{ color: "var(--ink)" }}>
              Your restore points
            </h3>
            <p
              className="mb-3 mt-1 text-[0.8rem]"
              style={{ color: "var(--ink-3)" }}
              data-testid="restore-point-capacity"
            >
              {manualCount} of {cap} captures used.{" "}
              <span style={{ color: "var(--ink-4)" }}>
                Backups taken before an update or a restore do not count here. Once they and your
                captures pass {cap}, the oldest backup is removed, but never the newest one. Your
                own captures are never removed.
              </span>
            </p>
          </>
        )}

        {canManage && (
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <input
              type="text"
              className="af-input min-w-[14rem] flex-1"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Label (optional)"
              aria-label="Restore point label"
              maxLength={120}
              disabled={captureBlockedReason !== null}
            />
            {captureBlockedReason ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span tabIndex={0} data-testid="capture-action">
                    {captureButton}
                  </span>
                </TooltipTrigger>
                <TooltipContent>{captureBlockedReason}</TooltipContent>
              </Tooltip>
            ) : (
              captureButton
            )}
          </div>
        )}

        {canManage && failedBackup && (
          <div
            className="mb-5 rounded-xl p-3 text-[0.8rem]"
            style={{
              background: "color-mix(in srgb, var(--err) 5%, transparent)",
              border: "1px solid color-mix(in srgb, var(--err) 35%, var(--line))",
              color: "var(--ink-2)",
            }}
            role="alert"
            data-testid="restore-backup-failed"
          >
            <div className="font-medium">The backup snapshot failed, so nothing was restored</div>
            <p className="mb-0 mt-1" style={{ color: "var(--ink-3)" }}>
              {failedBackup.failureReason ?? "No reason was given."}
            </p>
            <p className="mb-0 mt-1" style={{ color: "var(--ink-3)" }}>
              You can restore without it, but the current files cannot be brought back afterwards.
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="af-btn af-btn-sm"
                style={{ borderColor: "var(--err)", color: "var(--err)" }}
                disabled={isRunning || restoreWithoutBackup.isPending}
                data-testid="restore-without-backup-button"
                onClick={() => void restoreWithoutBackupSnapshot()}
              >
                {restoreWithoutBackup.isPending ? "Starting…" : "Restore without backup snapshot"}
              </button>
              <button type="button" className="af-btn af-btn-sm" onClick={() => setStartedRestore(null)}>
                Dismiss
              </button>
            </div>
          </div>
        )}

        {isLoading && (
          <div className="h-24 animate-pulse rounded-xl" style={{ background: "var(--bg-soft)" }} />
        )}

        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load this Agent's restore points"
            onRetry={() => void refetch()}
          />
        )}

        {!isLoading && !error && otherRestorePoints.length === 0 && (
          <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
            No restore points yet.
            {canManage
              ? " Capture one while the Agent is stopped to give yourself something to roll back to."
              : " Someone with Start/stop permission can capture one."}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {otherRestorePoints.map(renderRow)}
        </div>

        {hasMore && (
          <button
            type="button"
            className="af-btn af-btn-sm mt-3"
            disabled={isLoadingMore}
            onClick={loadMore}
          >
            {isLoadingMore ? "Loading…" : "Load more"}
          </button>
        )}
      </AgentConfigurationSection>

      <RestorePointRestoreDialog
        key={restoreTarget?.id ?? "none"}
        agent={agent}
        restorePoint={restoreTarget}
        canEditConfiguration={canEditConfiguration}
        onOpenChange={(open) => {
          if (!open) setRestoreTarget(null);
        }}
        onRestoreStarted={(started) => {
          setStartedRestore({ ...started, knownBackupIds: backupIdsWhenOpened });
          setRestoreTarget(null);
        }}
      />

      <ConfirmationDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        variant="destructive"
        title="Delete this restore point?"
        description={
          deleteTarget
            ? `“${restorePointLabel(deleteTarget)}” and its stored archive are removed permanently. The Agent's current files are untouched.`
            : ""
        }
        confirmLabel="Delete restore point"
        pendingLabel="Deleting…"
        isPending={deleteRestorePoint.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
