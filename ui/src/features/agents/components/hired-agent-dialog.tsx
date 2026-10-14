"use client";

import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import type { HiredAgent } from "../hooks/use-hire-agent-form";
import { DialogShell } from "./hire-dialog-primitives";

export function HiredAgentDialog({ agent, onClose, onHired }: {
  agent: HiredAgent;
  onClose: () => void;
  onHired: (agent: HiredAgent) => void;
}) {
  const router = useRouter();
  const { selectedOrganization } = useOrganizationContext();

  function openAgent(telegram: boolean) {
    const base = `/dashboard/${selectedOrganization!.id}/agents/${agent.id}`;
    onHired(agent);
    router.push(telegram ? `${base}/configuration?section=channels&connect=true` : `${base}?tab=chat`);
  }

  return (
    <DialogShell shadeClick={onClose}>
      <header className="flex items-start justify-between gap-4 border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <h2 className="m-0 text-xl font-semibold">{agent.name} is ready</h2>
        <button type="button" className="af-btn af-btn-ghost af-btn-icon" aria-label="Close hiring dialog" onClick={onClose}><X size={18} aria-hidden /></button>
      </header>
      <div className="flex items-start gap-3 overflow-y-auto p-6">
        <Check size={22} aria-hidden style={{ color: "var(--ok)" }} />
        <p className="m-0 leading-relaxed">Start chatting on the web, or connect Telegram. You can add more channels and change your assistant&apos;s settings later.</p>
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" onClick={() => openAgent(true)}>Connect Telegram</button>
        <button type="button" className="af-btn af-btn-primary" onClick={() => openAgent(false)}>Chat on the web</button>
      </footer>
    </DialogShell>
  );
}
