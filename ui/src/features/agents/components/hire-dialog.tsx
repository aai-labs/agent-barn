"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, WandSparkles, Wrench, X } from "lucide-react";

import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import type { HiredAgent } from "../hooks/use-hire-agent-form";
import { DialogShell } from "./hire-dialog-primitives";
import { HireFormDialog } from "./hire-form-dialog";
import { ReadyMadeAgentDialog } from "./ready-made-agent-dialog";

export type HireChoice = "ready" | "custom";

export function HireDialog({ onClose, onHired, initialChoice = "ready" }: {
  onClose: () => void;
  onHired: (agent: HiredAgent) => void;
  initialChoice?: HireChoice;
}) {
  const router = useRouter();
  const { selectedOrganization } = useOrganizationContext();
  const isTrial = Boolean(selectedOrganization?.isTrial);
  const { organization, isLoading, isFetching, error, refetch } = useOrganization(isTrial ? selectedOrganization!.id : "");
  const [selected, setSelected] = useState<HireChoice>(initialChoice);
  const [started, setStarted] = useState<HireChoice | null>(null);
  // Once creation starts, capacity may become full because of this very Agent.
  // Keep the mounted form so a failed start can retry that Agent rather than create another.
  if (started === "custom") return <HireFormDialog onClose={onClose} onHired={onHired} />;
  if (started === "ready") return <ReadyMadeAgentDialog onClose={onClose} onHired={onHired} />;

  const limit = organization?.trialAgentLimit;
  const full = isTrial && organization?.trialAgentLimitReached === true;
  const checking = isTrial && (isLoading || isFetching);
  const unavailable = isTrial && !checking && (Boolean(error) || organization?.trialAgentLimitReached === undefined || limit == null);
  const disabled = checking || unavailable || full;

  return (
    <DialogShell shadeClick={onClose}>
      <header className="flex items-start justify-between gap-4 border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">How would you like to start?</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>A ready-made assistant, or an agent built your way.</p>
        </div>
        <button type="button" aria-label="Close hiring dialog" className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}><X size={18} aria-hidden /></button>
      </header>
      <div className="overflow-y-auto p-6">
        {checking && <p role="status">Checking your trial&apos;s agent limit…</p>}
        {unavailable && <div role="alert" className="mb-5"><p>We couldn&apos;t check your trial&apos;s agent limit.</p><button type="button" className="af-btn" onClick={() => void refetch()}>Try again</button></div>}
        {full && (
          <div role="status" className="mb-5 rounded-xl border p-4" style={{ background: "var(--warn-soft)", borderColor: "var(--line)", color: "var(--ink-2)" }}>
            <p className="m-0 font-semibold">Your trial includes {limit} {limit === 1 ? "agent" : "agents"}, and you&apos;re using {limit === 1 ? "it" : "all of them"}.</p>
            <p className="mb-0 mt-2 text-sm">To try a different agent, delete an existing agent to free a slot. Stopping an agent doesn&apos;t free a slot.</p>
            <p className="mb-0 mt-2 text-sm">If you can&apos;t see or delete it, ask an organization owner.</p>
          </div>
        )}
        <div role="radiogroup" aria-label="How to hire" className="grid gap-3 sm:grid-cols-2">
          {([
            { value: "ready", icon: WandSparkles, title: "Ready-made assistant", description: "A general-purpose assistant on Hermes, using your organization's default model. Chat on the web or connect Telegram afterward." },
            { value: "custom", icon: Wrench, title: "Build your own", description: "Choose your template, runtime, model and skills. Add channels whenever you're ready." },
          ] as const).map(({ value, icon: Icon, title, description }) => (
            <button key={value} type="button" role="radio" aria-checked={selected === value} data-choice={value} tabIndex={selected === value ? 0 : -1} disabled={disabled} onClick={() => setSelected(value)} onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
              event.preventDefault();
              const next = value === "ready" ? "custom" : "ready";
              setSelected(next);
              event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-choice="${next}"]`)?.focus();
            }} className="flex flex-col items-start gap-3 rounded-xl border p-5 text-left disabled:cursor-not-allowed disabled:opacity-60" style={{ borderColor: selected === value ? "var(--ink)" : "var(--line)", background: selected === value ? "var(--bg-soft)" : "var(--bg-elev)" }}>
              <span className="flex w-full items-center justify-between"><Icon size={22} aria-hidden />{selected === value && <Check size={16} aria-hidden />}</span>
              <span className="font-semibold">{title}</span>
              <span className="text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>{description}</span>
            </button>
          ))}
        </div>
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" onClick={onClose}>Cancel</button>
        {full ? (
          <button type="button" className="af-btn af-btn-primary" onClick={() => { onClose(); router.push(`/dashboard/${selectedOrganization!.id}`); }}>View your agents</button>
        ) : (
          <button type="button" className="af-btn af-btn-primary" disabled={disabled} onClick={() => setStarted(selected)}>Continue <ArrowRight size={16} aria-hidden /></button>
        )}
      </footer>
    </DialogShell>
  );
}
