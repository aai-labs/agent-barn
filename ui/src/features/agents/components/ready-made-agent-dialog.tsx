"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";

import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import { useAgentNameSuggestion } from "../hooks/use-agent-name-suggestion";
import { useCreateAgent } from "../hooks/use-create-agent";
import type { HiredAgent } from "../hooks/use-hire-agent-form";
import { useStartAgent } from "../hooks/use-start-agent";
import { formatAgentName } from "../naming";
import { provisioningFailureOf } from "../provisioning-failure";
import type { AgentProvisioningError } from "../schemas";
import { AgentErrorBanner } from "./agent-error-banner";
import { DialogShell, FormField } from "./hire-dialog-primitives";

export function ReadyMadeAgentDialog({ onClose, onHired }: { onClose: () => void; onHired: (agent: HiredAgent) => void }) {
  const router = useRouter();
  const { selectedOrganization } = useOrganizationContext();
  const suggestion = useAgentNameSuggestion();
  const create = useCreateAgent();
  const start = useStartAgent();
  const [manualName, setManualName] = useState<string | null>(null);
  const [created, setCreated] = useState<HiredAgent | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failure, setFailure] = useState<AgentProvisioningError | null>(null);
  const inFlight = useRef(false);
  const name = manualName ?? (suggestion.firstName ? formatAgentName(suggestion.firstName, "General Purpose") : "");
  const pending = create.isPending || start.isPending;

  async function hire() {
    if (inFlight.current || !name.trim()) return;
    inFlight.current = true;
    setError(null);
    setFailure(null);
    try {
      let agent = created;
      if (!agent) {
        const result = await create.mutateAsync({ name: name.trim(), agentType: "hermes", templateKey: "general-purpose", approvalMode: "auto" });
        agent = { id: result.id, name: result.name, role: "General Purpose" };
        setCreated(agent);
      }
      await start.mutateAsync(agent.id);
      setReady(true);
    } catch (cause) {
      const provisioningFailure = provisioningFailureOf(cause);
      if (provisioningFailure) setFailure(provisioningFailure);
      else setError(cause instanceof Error ? cause.message : "We couldn't prepare your assistant.");
    } finally {
      inFlight.current = false;
    }
  }

  function openAgent(telegram: boolean) {
    if (!created) return;
    const base = `/dashboard/${selectedOrganization!.id}/agents/${created.id}`;
    onHired(created);
    router.push(telegram ? `${base}/configuration?section=channels&connect=true` : `${base}?tab=chat`);
  }

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between gap-4 border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <h2 className="m-0 text-xl font-semibold">{ready ? `${created?.name} is ready` : "Your ready-made assistant"}</h2>
        <button type="button" className="af-btn af-btn-ghost af-btn-icon" aria-label="Close hiring dialog" disabled={pending} onClick={onClose}><X size={18} aria-hidden /></button>
      </header>
      <div className="overflow-y-auto p-6">
        {ready ? (
          <div className="flex items-start gap-3"><Check size={22} aria-hidden style={{ color: "var(--ok)" }} /><p className="m-0 leading-relaxed">Start chatting on the web, or connect Telegram. You can add more channels and change your assistant&apos;s settings later.</p></div>
        ) : (
          <>
            <p className="mb-5 mt-0 text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>A General Purpose assistant on Hermes, using your organization&apos;s default model. Give it a name and we&apos;ll get it running.</p>
            {!created && <FormField label="Agent name"><input aria-label="Agent name" className="af-input" value={name} maxLength={255} disabled={pending || suggestion.isLoading} onChange={(event) => setManualName(event.target.value)} />{suggestion.isLoading && <span role="status">Suggesting a name…</span>}{suggestion.error && <span className="text-sm">Enter a name, or <button type="button" className="underline" onClick={() => void suggestion.retry()}>retry name suggestion</button>.</span>}</FormField>}
            {failure && <AgentErrorBanner failure={failure} className="mt-4" />}
            {error && <p role="alert" className="mb-0 mt-4 text-sm" style={{ color: "var(--err)" }}>{error}</p>}
            {created && <p className="mb-0 mt-4 text-sm">{created.name} was created. If startup fails, retrying starts this same agent.</p>}
          </>
        )}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        {ready ? <><button type="button" className="af-btn" onClick={() => openAgent(true)}>Connect Telegram</button><button type="button" className="af-btn af-btn-primary" onClick={() => openAgent(false)}>Chat on the web</button></> : <><button type="button" className="af-btn" disabled={pending} onClick={onClose}>Cancel</button><button type="button" className="af-btn af-btn-primary" disabled={pending || !name.trim()} onClick={() => void hire()}>{pending ? "Preparing…" : created ? "Start again" : "Create assistant"}</button></>}
      </footer>
    </DialogShell>
  );
}
