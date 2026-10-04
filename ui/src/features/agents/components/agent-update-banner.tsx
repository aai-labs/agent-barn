"use client";

import { RotateCcw, Sparkles } from "lucide-react";

import { toastError } from "@/shared/toast";

import { useManagedUpdate } from "../hooks/use-managed-update";
import type { Agent } from "../schemas";

const RELEASES_URL = "https://github.com/aai-labs/agent-barn/releases";

export function AgentUpdateBanner({ agent }: { agent: Agent }) {
  const managedUpdate = useManagedUpdate();

  if (!agent.updateAvailable && !managedUpdate.isPending) {
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
        disabled={managedUpdate.isPending}
        onClick={update}
      >
        <RotateCcw size={14} /> {managedUpdate.isPending ? "Updating…" : "Update"}
      </button>
    </div>
  );
}
