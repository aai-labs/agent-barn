"use client";

import Link from "next/link";
import { RotateCcw, Sparkles } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { toastError } from "@/shared/toast";

import { useManagedUpdate } from "../hooks/use-managed-update";
import type { Agent } from "../schemas";

const RELEASES_URL = "https://github.com/aai-labs/agent-barn/releases";

export function AgentUpdateBanner({ agent }: { agent: Agent }) {
  const managedUpdate = useManagedUpdate();
  // The server's flag covers the whole run, including the minutes after the
  // 202, so the button cannot start a second update meanwhile.
  const updating = agent.updateInProgress || managedUpdate.isPending;

  if (!agent.updateAvailable && !updating) {
    return null;
  }

  const update = () => void managedUpdate.mutateAsync(agent.id).catch(toastError);

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
          A new version of {agent.name} is available. Updating stops the Agent, saves a restore
          point of its current state, then starts the new version. If the new version does not
          come up healthy, it is rolled back automatically.{" "}
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
        <RotateCcw size={14} /> {updating ? "Updating…" : "Update"}
      </button>
    </div>
  );
}

/**
 * The same offer as AgentUpdateBanner, compact enough for a top bar: a button that
 * says an update is available and opens the explanation with the Update action.
 */
export function AgentUpdateNotice({ agent }: { agent: Agent }) {
  const managedUpdate = useManagedUpdate();
  const updating = agent.updateInProgress || managedUpdate.isPending;

  if (!agent.updateAvailable && !updating) {
    return null;
  }

  const update = () => void managedUpdate.mutateAsync(agent.id).catch(toastError);

  if (updating) {
    return (
      <span
        data-testid="agent-update-notice"
        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium"
        style={{ background: "var(--accent-soft)", color: "var(--accent-ink)" }}
      >
        <RotateCcw size={13} className="animate-spin" aria-hidden /> Updating…
      </span>
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="agent-update-notice"
          className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent-ink)",
            border: "1px solid color-mix(in srgb, var(--accent-color) 25%, transparent)",
          }}
        >
          <Sparkles size={13} aria-hidden /> Update available
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <p className="m-0 text-[0.844rem] leading-relaxed" style={{ color: "var(--ink-2)" }}>
          A new version of {agent.name} is available. Updating stops the Agent, saves a restore
          point of its current state, then starts the new version. If the new version does not
          come up healthy, it is rolled back automatically.
        </p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <a
            href={RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[0.8125rem] font-medium underline underline-offset-3"
            style={{ color: "var(--accent-ink)" }}
          >
            Release notes
          </a>
          <button className="af-btn af-btn-primary af-btn-sm" onClick={update}>
            <RotateCcw size={14} /> Update
          </button>
        </div>
      </PopoverContent>
    </Popover>
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
    message = (
      <>
        The last update did not come up healthy, so {agent.name} was rolled back to the version and
        files it had before. It is running as before.
      </>
    );
  } else if (last.outcome === "BACKUP_FAILED") {
    message = (
      <>
        The last update was not applied because the automatic backup could not be taken
        {last.failureReason ? `: ${last.failureReason}` : "."}{" "}
        {agent.status === "STOPPED" &&
          `${agent.name} was stopped but not changed. Start it to keep using the current version.`}
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
