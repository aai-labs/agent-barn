"use client";

import { useState } from "react";
import { RotateCcw } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Checkbox } from "@/components/ui/checkbox";

import { useRestoreRestorePoint } from "../hooks/use-restore-point-actions";
import type { Agent, RestorePoint } from "../schemas";
import { isReplayable, nameSkillsInMessage, restorePointLabel } from "./restore-point-utils";

// Keyed on the target in the parent, so a different restore point mounts fresh.
export function RestorePointRestoreDialog({
  agent,
  restorePoint,
  canEditConfiguration,
  onOpenChange,
  onRestoreStarted,
}: {
  agent: Agent;
  restorePoint: RestorePoint | null;
  canEditConfiguration: boolean;
  onOpenChange: (open: boolean) => void;
  onRestoreStarted: () => void;
}) {
  const restore = useRestoreRestorePoint(agent.id);
  const [typedName, setTypedName] = useState("");
  const [reapply, setReapply] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const open = restorePoint !== null;
  // Replay writes configuration — a separate permission from the lifecycle one.
  const replayable =
    restorePoint !== null && canEditConfiguration && isReplayable(restorePoint.configManifest);

  async function confirm() {
    if (!restorePoint) return;
    setFailure(null);
    try {
      await restore.mutateAsync({
        restorePointId: restorePoint.id,
        reapplyConfiguration: reapply && replayable,
      });
    } catch (error) {
      // The server checks the recorded configuration before it starts the Job, so a
      // refusal here means nothing has been overwritten and this dialog can simply
      // stay open.
      setFailure(
        error instanceof Error
          ? nameSkillsInMessage(error.message, restorePoint.configManifest.skills)
          : "The restore could not be started.",
      );
      return;
    }
    onRestoreStarted();
    onOpenChange(false);
  }

  return (
    <ConfirmationDialog
      open={open}
      onOpenChange={onOpenChange}
      variant="destructive"
      icon={<RotateCcw size={18} />}
      title={`Restore ${agent.name} from this restore point?`}
      description={
        restorePoint
          ? `“${restorePointLabel(restorePoint)}” replaces everything on the Agent's volume.`
          : ""
      }
      confirmLabel="Restore Agent"
      pendingLabel="Starting…"
      confirmDisabled={typedName !== agent.name}
      isPending={restore.isPending}
      onConfirm={() => void confirm()}
    >
      <div className="mt-4 flex flex-col gap-4">
        <div
          className="rounded-xl p-3 text-[0.8rem]"
          style={{
            background: "color-mix(in srgb, var(--err) 5%, transparent)",
            border: "1px solid color-mix(in srgb, var(--err) 35%, var(--line))",
            color: "var(--ink-2)",
          }}
        >
          <div className="font-medium">This replaces, on the Agent&apos;s volume:</div>
          <ul className="mb-0 mt-1.5 list-disc pl-4" style={{ color: "var(--ink-3)" }}>
            <li>its working files</li>
            <li>its memories</li>
            <li>its runtime session history</li>
          </ul>
          <p className="mb-0 mt-2" style={{ color: "var(--ink-3)" }}>
            The runtime&apos;s own session history rolls back with the volume, but the
            conversation history recorded here does not. Afterwards this record runs ahead
            of what the Agent itself remembers — the record is the audit trail, and it is
            meant to stay complete.
          </p>
          <p className="mb-0 mt-2" style={{ color: "var(--ink-3)" }}>
            A backup of the current volume is captured automatically first.
          </p>
        </div>

        {replayable && (
          <label className="flex cursor-pointer items-start gap-2.5">
            <Checkbox
              checked={reapply}
              onCheckedChange={(checked) => setReapply(checked === true)}
              aria-label="Also re-apply the recorded configuration"
            />
            <span className="text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
              Also re-apply the recorded configuration
              <span className="mt-0.5 block" style={{ color: "var(--ink-4)" }}>
                Checked now, and applied once the files are back. Off by default: only the
                volume rolls back otherwise.
              </span>
            </span>
          </label>
        )}

        {failure && (
          <div
            className="rounded-xl p-3 text-[0.8rem]"
            style={{
              background: "color-mix(in srgb, var(--err) 5%, transparent)",
              border: "1px solid color-mix(in srgb, var(--err) 35%, var(--line))",
              color: "var(--err)",
            }}
            role="alert"
          >
            <div className="font-medium">The restore was not started</div>
            <p className="mb-0 mt-1" style={{ color: "var(--ink-2)" }}>
              {failure}
            </p>
            <p className="mb-0 mt-1.5" style={{ color: "var(--ink-3)" }}>
              Nothing on the Agent&apos;s volume has been changed.
            </p>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label
            className="text-[0.8rem] font-medium"
            style={{ color: "var(--ink-2)" }}
            htmlFor="restore-confirm-name"
          >
            Type <strong>{agent.name}</strong> to confirm
          </label>
          <input
            id="restore-confirm-name"
            type="text"
            className="af-input w-full"
            value={typedName}
            onChange={(event) => setTypedName(event.target.value)}
            placeholder={agent.name}
            autoComplete="off"
          />
        </div>
      </div>
    </ConfirmationDialog>
  );
}
