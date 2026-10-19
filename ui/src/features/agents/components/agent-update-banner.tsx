"use client";

import { useState } from "react";
import Link from "next/link";
import { RotateCcw, Sparkles } from "lucide-react";

import { toastError } from "@/shared/toast";

import { useManagedUpdate } from "../hooks/use-managed-update";
import type { Agent } from "../schemas";
import { shortFailureReason } from "./restore-point-utils";

const RELEASES_URL = "https://github.com/aai-labs/agent-barn/releases";

export function AgentUpdateBanner({ agent }: { agent: Agent }) {
  const managedUpdate = useManagedUpdate();
  // The server's flag covers the whole run, including the minutes after the
  // 202, so the button cannot start a second update meanwhile.
  const updating = agent.updateInProgress || managedUpdate.isPending;
  // Kept only here, on purpose: after a reload the banner offers a normal update again.
  const [startedHere, setStartedHere] = useState(false);
  // A failed backup leaves the Agent stopped, and a stopped Agent never reports an update as
  // available, so the failure is what keeps the banner on screen.
  const backupFailed =
    startedHere &&
    !updating &&
    agent.status === "STOPPED" &&
    agent.lastManagedUpdate?.outcome === "BACKUP_FAILED";

  if (!agent.updateAvailable && !updating && !backupFailed) {
    return null;
  }

  const update = () => {
    setStartedHere(true);
    void managedUpdate.mutateAsync({ agentId: agent.id, skipBackup: backupFailed }).catch(toastError);
  };

  return (
    <div
      data-testid="agent-update-banner"
      className="mb-6 flex items-center justify-between gap-3 rounded-2xl px-4 py-3.5"
      style={{
        background: "var(--accent-soft)",
        border: "1px solid color-mix(in srgb, var(--accent-color) 25%, transparent)",
      }}
    >
      <div className="flex items-center gap-3">
        <span
          className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-lg"
          style={{
            background: "color-mix(in srgb, var(--accent-color) 14%, transparent)",
            color: "var(--accent-color)",
          }}
        >
          <Sparkles size={16} />
        </span>
        <p className="m-0 text-[0.844rem] leading-relaxed" style={{ color: "var(--accent-ink)" }}>
          {backupFailed ? (
            <>
              The backup snapshot failed. You can update without it, but if the new version does
              not come up healthy, {agent.name} restarts on its old version and its files are not
              rolled back.{" "}
            </>
          ) : (
            <>
              A new version of {agent.name} is available. Updating stops the Agent, saves a restore
              point of its current state, then starts the new version. If the new version does not
              come up healthy, it is rolled back automatically.{" "}
            </>
          )}
          <a
            href={RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="agent-update-releases-link"
            className="font-medium underline underline-offset-3"
          >
            Release notes
          </a>
        </p>
      </div>
      <button
        className="af-btn af-btn-primary af-btn-sm flex-shrink-0"
        data-testid="agent-update-button"
        disabled={updating}
        onClick={update}
      >
        <RotateCcw size={14} />{" "}
        {updating ? "Updating…" : backupFailed ? "Update without backup snapshot" : "Update"}
      </button>
    </div>
  );
}

/**
 * How the last managed update ended, while the Agent is still in the state it
 * left. Success needs no note: the banner going away says it.
 */
export function AgentUpdateOutcomeNote({
  agent,
  restorePointsHref,
}: {
  agent: Agent;
  restorePointsHref: string;
}) {
  const last = agent.lastManagedUpdate;
  if (!last || agent.updateInProgress) {
    return null;
  }

  let message: React.ReactNode = null;
  if (last.outcome === "ROLLED_BACK" && agent.status === "RUNNING") {
    message = last.restorePointId ? (
      <>
        The last update did not come up healthy, so {agent.name} was rolled back to the version and
        files it had before. It is running as before.
      </>
    ) : (
      <>
        The last update, run without a backup, did not come up healthy, so {agent.name} was
        restarted on the version it had before. Its files were not rolled back.
      </>
    );
  } else if (last.outcome === "BACKUP_FAILED") {
    message = (
      <>
        The last update was not applied because the automatic backup could not be taken
        {last.failureReason ? ` (${shortFailureReason(last.failureReason).replace(/\.$/, "")}).` : "."}{" "}
        {agent.status === "STOPPED" &&
          `${agent.name} was stopped but not changed. Start it to keep using the current version.`}
      </>
    );
  } else if (last.outcome === "ROLLBACK_FAILED" && agent.status !== "RUNNING" && !last.restorePointId) {
    message = (
      <>
        The update, run without a backup, failed and {agent.name} could not be restarted on its
        previous version. There is no backup to restore. Start the Agent to try again.
      </>
    );
  } else if (last.outcome === "ROLLBACK_FAILED" && agent.status !== "RUNNING") {
    message = (
      <>
        The update failed and the automatic rollback did not finish. {agent.name}&apos;s files from
        before the update are safe in the restore point &ldquo;Automatic backup before managed
        update&rdquo;. Restore it, then start the Agent.{" "}
        <Link href={restorePointsHref} className="font-medium underline underline-offset-3">
          Go to restore points
        </Link>
      </>
    );
  }
  if (!message) {
    return null;
  }

  return (
    <div
      data-testid="agent-update-outcome"
      data-outcome={last.outcome}
      className="mb-6 rounded-2xl px-4 py-3.5 text-[0.844rem] leading-relaxed"
      style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
    >
      {message}
    </div>
  );
}
