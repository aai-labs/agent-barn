"use client";

import { RotateCcw, Sparkles } from "lucide-react";

import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import type { Agent } from "../schemas";

const RELEASES_URL = "https://github.com/aai-labs/agent-barn/releases";

export function AgentUpdateBanner({ agent }: { agent: Agent }) {
  const restartAgent = useRestartAgent();

  if (!agent.updateAvailable && !restartAgent.isPending) {
    return null;
  }

  const update = () => void restartAgent.restart(agent.id).catch(toastError);

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
          A new version of {agent.name} is available. Update to get the latest bug fixes and
          features.{" "}
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
        disabled={restartAgent.isPending}
        onClick={update}
      >
        <RotateCcw size={14} /> {restartAgent.isPending ? "Updating…" : "Update"}
      </button>
    </div>
  );
}
