"use client";

import { useState } from "react";
import { RotateCcw } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { toastError } from "@/shared/toast";

import { useFetchAgent } from "../hooks/use-agent";
import { useSelectAgentTemplate } from "../hooks/use-agent-override-actions";
import { useRestoreRestorePoint } from "../hooks/use-restore-point-actions";
import type { Agent, RestorePoint } from "../schemas";
import { isReplayable, restorePointLabel } from "./restore-point-utils";

function approvalMode(value: string): Agent["approvalMode"] | undefined {
  return value === "manual" || value === "auto" || value === "off" ? value : undefined;
}

// Keyed on the target in the parent, so a different restore point mounts fresh.
export function RestorePointRestoreDialog({
  agent,
  restorePoint,
  canEditConfiguration,
  onOpenChange,
  onRestored,
}: {
  agent: Agent;
  restorePoint: RestorePoint | null;
  canEditConfiguration: boolean;
  onOpenChange: (open: boolean) => void;
  onRestored: () => void;
}) {
  const restore = useRestoreRestorePoint(agent.id);
  const selectTemplate = useSelectAgentTemplate();
  const fetchAgent = useFetchAgent();
  const [typedName, setTypedName] = useState("");
  const [reapply, setReapply] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // Re-submitting an accepted restore either conflicts with the running Job or,
  // once it finishes and the row returns to READY, starts a second one.
  const [restoreAccepted, setRestoreAccepted] = useState(false);
  // Spans the whole replay: between reading the Agent and submitting the selection
  // no mutation is pending, and dismissal is gated on this.
  const [isReplaying, setIsReplaying] = useState(false);

  const open = restorePoint !== null;
  // Replay writes configuration — a separate permission from the lifecycle one.
  const replayable =
    restorePoint !== null && canEditConfiguration && isReplayable(restorePoint.configManifest);

  /**
   * One request, because required skill pins are validated against the assignments
   * the Agent will have: split in two, each half is judged against the other's
   * unwritten state.
   */
  async function applyRecordedConfiguration(target: RestorePoint) {
    setIsReplaying(true);
    try {
      return await runRecordedConfiguration(target);
    } finally {
      setIsReplaying(false);
    }
  }

  async function runRecordedConfiguration(target: RestorePoint) {
    const manifest = target.configManifest;
    const recordedSkillIds = manifest.skills.map((skill) => skill.skillId);

    let current: Agent;
    try {
      // A read taken now, not the snapshot this dialog opened with.
      current = await fetchAgent(agent.id);
    } catch (error) {
      return error instanceof Error
        ? error.message
        : "The Agent's current configuration could not be read.";
    }

    const settings = {
      agentId: agent.id,
      expectedAgentUpdatedAt: current.updatedAt,
      model: manifest.model || null,
      approvalMode: approvalMode(manifest.approvalMode),
      verboseMode: manifest.verboseMode,
      skillIds: recordedSkillIds,
      removedSkillIds: current.skills
        .map((skill) => skill.id)
        .filter((id) => !recordedSkillIds.includes(id)),
      skillVersions: manifest.skills.map((skill) => ({
        skillId: skill.skillId,
        version: skill.pinnedVersion,
      })),
    };

    try {
      if (manifest.templateSelectionType === "override") {
        await selectTemplate.mutateAsync({
          ...settings,
          selectionType: "override",
          overrideVersion: manifest.overrideVersion ?? manifest.templateVersion,
        });
      } else {
        await selectTemplate.mutateAsync({
          ...settings,
          // The recorded scope, not a lookup by key: a fork shares its platform
          // lineage's key and restarts at v1.
          selectionType: manifest.templateSelectionType as "platform" | "organization",
          templateKey: manifest.templateKey,
          templateVersion: manifest.templateVersion,
        });
      }
      return null;
    } catch (error) {
      return error instanceof Error
        ? error.message
        : "The recorded configuration could not be re-applied.";
    }
  }

  async function confirm() {
    if (!restorePoint) return;
    setFailure(null);

    try {
      await restore.mutateAsync(restorePoint.id);
    } catch (error) {
      toastError(error);
      return;
    }
    setRestoreAccepted(true);

    if (reapply && replayable) {
      const replayFailure = await applyRecordedConfiguration(restorePoint);
      if (replayFailure) {
        setFailure(replayFailure);
        return;
      }
    }

    onRestored();
    onOpenChange(false);
  }

  async function retryConfiguration() {
    if (!restorePoint) return;
    setFailure(null);
    const replayFailure = await applyRecordedConfiguration(restorePoint);
    if (replayFailure) {
      setFailure(replayFailure);
      return;
    }
    onRestored();
    onOpenChange(false);
  }

  const isPending = restore.isPending || selectTemplate.isPending || isReplaying;

  return (
    <ConfirmationDialog
      open={open}
      onOpenChange={onOpenChange}
      variant={restoreAccepted ? "default" : "destructive"}
      icon={<RotateCcw size={18} />}
      title={
        restoreAccepted
          ? "Restore started"
          : `Restore ${agent.name} from this restore point?`
      }
      description={
        restorePoint
          ? restoreAccepted
            ? `The Agent's volume is being replaced from “${restorePointLabel(restorePoint)}”.`
            : `“${restorePointLabel(restorePoint)}” replaces everything on the Agent's volume.`
          : ""
      }
      confirmLabel={restoreAccepted ? "Done" : "Restore Agent"}
      pendingLabel="Restoring…"
      confirmDisabled={restoreAccepted ? false : typedName !== agent.name}
      isPending={isPending}
      onConfirm={restoreAccepted ? () => onOpenChange(false) : () => void confirm()}
    >
      <div className="mt-4 flex flex-col gap-4">
        {!restoreAccepted && (
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
        )}

        {replayable && !restoreAccepted && (
          <label className="flex cursor-pointer items-start gap-2.5">
            <Checkbox
              checked={reapply}
              onCheckedChange={(checked) => setReapply(checked === true)}
              aria-label="Also re-apply the recorded configuration"
            />
            <span className="text-[0.8rem]" style={{ color: "var(--ink-2)" }}>
              Also re-apply the recorded configuration
              <span className="mt-0.5 block" style={{ color: "var(--ink-4)" }}>
                Re-pins the template, model, skills, and approval settings the Agent had
                when this restore point was captured. Off by default: only the volume rolls
                back otherwise.
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
            <div className="font-medium">The recorded configuration was not re-applied</div>
            <p className="mb-0 mt-1" style={{ color: "var(--ink-2)" }}>
              The Agent&apos;s configuration is unchanged: it is applied as one request,
              so it either lands whole or not at all.
            </p>
            <p className="mb-0 mt-1.5" style={{ color: "var(--ink-2)" }}>{failure}</p>
            <p className="mb-0 mt-1.5" style={{ color: "var(--ink-3)" }}>
              The volume restore is unaffected and is still running.
            </p>
            <button
              type="button"
              className="af-btn af-btn-sm mt-2.5"
              disabled={isPending}
              onClick={() => void retryConfiguration()}
            >
              Retry configuration
            </button>
          </div>
        )}

        {!restoreAccepted && (
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
        )}
      </div>
    </ConfirmationDialog>
  );
}
