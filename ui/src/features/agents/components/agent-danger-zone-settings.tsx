"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { toastError } from "@/shared/toast";
import { useDeleteAgent } from "../hooks/use-delete-agent";
import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";
import { RetireAgentDialog } from "./retire-agent-dialog";

export function AgentDangerZoneSettings({ agent, canDelete, homeHref }: { agent: Agent; canDelete: boolean; homeHref: string }) {
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const [retireOpen, setRetireOpen] = useState(false);

  async function retire() {
    try {
      await deleteAgent.mutateAsync(agent.id);
      router.push(homeHref);
    } catch (error) {
      toastError(error);
    }
  }

  return (
    <>
      <AgentConfigurationSection
        title="Danger zone"
        description="These actions affect the Agent itself and cannot be undone."
      >
        <div className="rounded-xl p-4" style={{ border: "1px solid color-mix(in srgb, var(--err) 35%, var(--line))", background: "color-mix(in srgb, var(--err) 5%, transparent)" }}>
          <div className="font-medium text-[0.9rem]" style={{ color: "var(--err)" }}>Retire this Agent</div>
          <p className="mb-4 mt-1 text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
            Permanently remove the Agent, its managed runtime resources, and everything it has learned. You
            can copy its memory to another Agent first.
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
      <RetireAgentDialog
        open={retireOpen}
        onOpenChange={setRetireOpen}
        agent={agent}
        onRetire={retire}
        isRetiring={deleteAgent.isPending}
      />
    </>
  );
}
