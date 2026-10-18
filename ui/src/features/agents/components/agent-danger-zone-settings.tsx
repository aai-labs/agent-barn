"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { toastError } from "@/shared/toast";
import { useDeleteAgent } from "../hooks/use-delete-agent";
import { useResetAgent } from "../hooks/use-restore-point-actions";
import { isRestorePointBusy, useRestorePoints } from "../hooks/use-restore-points";
import { useSharePointAccess } from "../hooks/use-sharepoint-sign-in";
import type { Agent, RestorePoint } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";

const DANGER_BLOCK_STYLE = {
  border: "1px solid color-mix(in srgb, var(--err) 35%, var(--line))",
  background: "color-mix(in srgb, var(--err) 5%, transparent)",
};

/**
 * What to tell someone whose reset did not finish, or null if it did. A failed backup row says
 * so itself; a ready one carries a reason only when the reset took its backup and then stopped.
 */
function didNotFinishText(restorePoint: RestorePoint): string | null {
  if (restorePoint.status === "FAILED") {
    return `The reset did not complete. ${restorePoint.failureReason ?? ""}`.trim();
  }
  return restorePoint.failureReason;
}

export function AgentDangerZoneSettings({
  agent,
  canDelete,
  canReset,
  canReadActivity,
  homeHref,
}: {
  agent: Agent;
  canDelete: boolean;
  canReset: boolean;
  canReadActivity: boolean;
  homeHref: string;
}) {
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const resetAgent = useResetAgent(agent.id);
  const [retireOpen, setRetireOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  // The backup this page's own reset took. The success note is tied to it so it does
  // not come back when the Agent is stopped again weeks later.
  const [resetBackupId, setResetBackupId] = useState<string | null>(null);
  const sharepointAccess = useSharePointAccess(agent.id, {
    enabled: (agent.secrets ?? []).some((secret) => secret.provider === "sharepoint"),
  });
  const sharepointSites = sharepointAccess.data?.mode === "selected_sites" ? sharepointAccess.data.sites : [];

  // The Job runs in the background; the backup row it is tracked by is what says how it went.
  const { restorePoints } = useRestorePoints(agent.id, canReadActivity);
  const latestReset = restorePoints.find((restorePoint) => restorePoint.origin === "PRE_RESET");
  const resetRunning = resetAgent.isPending || (latestReset !== undefined && isRestorePointBusy(latestReset));
  const restorePointsHref = `${homeHref}/agents/${agent.id}/configuration?section=restore`;

  // Stated up front rather than discovered through a 409.
  function resetBlockedReason(): string | null {
    if (!canReset) return "You need permission to manage this Agent's lifecycle to reset it.";
    if (agent.status === "RUNNING") return "Stop the Agent before resetting it.";
    if (agent.updateInProgress) return "A managed update is running. Wait for it to finish.";
    if (resetRunning) return null;
    if (restorePoints.some(isRestorePointBusy)) return "A capture or restore is already running for this Agent.";
    return null;
  }

  const blockedReason = resetBlockedReason();

  // Only a reset that is still the latest thing to happen to the volume is worth a note. One that
  // did not finish stays on show even once the Agent runs: starting the Agent is what used to hide
  // the failure from the person who asked for it. A success is only news until the Agent starts.
  const latestIsSettled = latestReset !== undefined && latestReset.id === restorePoints[0]?.id && !resetRunning;
  let outcome: string | null = null;
  if (latestIsSettled && didNotFinishText(latestReset) !== null) {
    outcome = didNotFinishText(latestReset);
  } else if (latestIsSettled && agent.status !== "RUNNING" && latestReset.id === resetBackupId) {
    outcome = "Reset finished. Start the Agent to boot it fresh.";
  }

  // Said once, when this page's own reset ends badly: by then the person is usually looking elsewhere.
  const ownReset = restorePoints.find((restorePoint) => restorePoint.id === resetBackupId);
  const ownResetProblem = ownReset !== undefined && !isRestorePointBusy(ownReset) ? didNotFinishText(ownReset) : null;
  const toldAbout = useRef<string | null>(null);
  useEffect(() => {
    if (ownReset === undefined || ownResetProblem === null || toldAbout.current === ownReset.id) return;
    toldAbout.current = ownReset.id;
    toast.error(ownResetProblem);
  }, [ownReset, ownResetProblem]);

  async function retire() {
    try {
      await deleteAgent.mutateAsync(agent.id);
      router.push(homeHref);
    } catch (error) {
      toastError(error);
    }
  }

  async function reset() {
    try {
      const backup = await resetAgent.mutateAsync();
      setResetBackupId(backup.id);
      setResetOpen(false);
    } catch (error) {
      toastError(error);
    }
  }

  return (
    <>
      <AgentConfigurationSection
        title="Danger zone"
        description="These actions change or remove the Agent itself."
      >
        <div className="rounded-xl p-4" style={DANGER_BLOCK_STYLE} data-testid="agent-reset">
          <div className="font-medium text-[0.9rem]" style={{ color: "var(--err)" }}>Reset this Agent</div>
          <p className="mb-4 mt-1 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
            Remove everything the Agent has saved on its own volume — chat sessions, scheduled jobs, notes and workspace
            files — and start it fresh from its settings. A “Before reset” backup of those files is saved first, so you
            can bring them back from Restore points. A backup does not hold what the Agent rebuilds when it starts (its
            template files, skills, keys and settings) or its queued outgoing messages.
          </p>
          <button
            type="button"
            className="af-btn af-btn-sm"
            style={{ borderColor: "var(--err)", color: "var(--err)" }}
            disabled={blockedReason !== null || resetRunning}
            data-testid="agent-reset-button"
            onClick={() => setResetOpen(true)}
          >
            {resetRunning ? (
              <>
                <Loader2 size={13} className="animate-spin" aria-hidden /> Resetting…
              </>
            ) : (
              "Reset Agent"
            )}
          </button>
          {blockedReason && (
            <p className="mb-0 mt-2 text-[0.8rem]" style={{ color: "var(--ink-4)" }} data-testid="agent-reset-reason">
              {blockedReason}
            </p>
          )}
          {outcome && (
            <p className="mb-0 mt-2 text-[0.8rem]" style={{ color: "var(--ink-2)" }} role="status" data-testid="agent-reset-outcome">
              {outcome}{" "}
              {canReadActivity && (
                <Link href={restorePointsHref} className="underline">
                  View the backup
                </Link>
              )}
            </p>
          )}
        </div>
        <div className="mt-3 rounded-xl p-4" style={DANGER_BLOCK_STYLE}>
          <div className="font-medium text-[0.9rem]" style={{ color: "var(--err)" }}>Retire this Agent</div>
          <p className="mb-4 mt-1 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
            Permanently remove the Agent and its managed runtime resources. This does not restore its configuration later.
          </p>
          {canDelete ? (
            <button type="button" className="af-btn af-btn-sm" style={{ borderColor: "var(--err)", color: "var(--err)" }} onClick={() => setRetireOpen(true)}>
              Retire Agent
            </button>
          ) : (
            <span className="text-[0.8rem]" style={{ color: "var(--ink-4)" }}>You need Agent owner permission to retire this Agent.</span>
          )}
        </div>
      </AgentConfigurationSection>
      <ConfirmationDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        title={`Reset ${agent.name}?`}
        description={
          "This removes everything the Agent saved on its own volume: chat sessions, scheduled jobs, notes and workspace files. " +
          "Its settings, skills, connections, conversation history in Agent Barn and long-term memory are kept. " +
          "A “Before reset” backup of those files is saved first and can be restored. It does not hold queued outgoing messages, " +
          "or what the Agent rebuilds when it starts (template files, skills, keys and settings). " +
          "The Agent stays stopped until you start it."
        }
        confirmLabel="Reset Agent"
        pendingLabel="Resetting…"
        variant="destructive"
        onConfirm={() => void reset()}
        isPending={resetAgent.isPending}
      />
      <ConfirmationDialog
        open={retireOpen}
        onOpenChange={setRetireOpen}
        title={`Retire ${agent.name}?`}
        description={
          "This permanently deletes the Agent's managed runtime resources and configuration. This action cannot be undone." +
          (sharepointSites.length > 0
            ? ` Its SharePoint sites (${sharepointSites.join(", ")}) stay granted to its Microsoft Teams app; to take them away, remove all sites under SharePoint in the agent's Integrations first.`
            : "")
        }
        confirmLabel="Retire Agent"
        pendingLabel="Retiring…"
        onConfirm={() => void retire()}
        isPending={deleteAgent.isPending}
      />
    </>
  );
}
