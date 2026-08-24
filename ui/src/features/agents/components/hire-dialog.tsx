"use client";

import { useState } from "react";
import { XIcon } from "@/components/icons";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

import { useCreateAgent } from "../hooks/use-create-agent";
import { useStartAgent } from "../hooks/use-start-agent";
import { useTemplates } from "../hooks/use-templates";
import { DialogShell, FormField } from "./hire-dialog-primitives";
import { ModelSelect } from "./model-select";

const DEFAULT_AGENT_NAME = "Aria";

interface HireDialogProps {
  onClose: () => void;
  onHired: (info: { name: string; role: string }) => void;
}

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const { templates, isLoading } = useTemplates();
  const createAgent = useCreateAgent();
  const startAgent = useStartAgent();
  const [name, setName] = useState(DEFAULT_AGENT_NAME);
  const [templateKey, setTemplateKey] = useState("");
  const [agentType, setAgentType] = useState<"openclaw" | "hermes">("hermes");
  const [model, setModel] = useState("");
  const [approvalMode, setApprovalMode] = useState<"manual" | "auto" | "off">("auto");
  const [error, setError] = useState<string | null>(null);

  const template = templates.find((candidate) => candidate.templateKey === templateKey);
  const pending = createAgent.isPending || startAgent.isPending;

  async function hire() {
    if (!template || !name.trim()) return;
    setError(null);
    try {
      const agent = await createAgent.mutateAsync({
        name: name.trim(),
        agentType,
        templateKey: template.templateKey,
        templateVersion: template.version,
        model,
        approvalMode,
      });
      await startAgent.mutateAsync(agent.id);
      onHired({ name: agent.name, role: template.templateName });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not hire the Agent.");
    }
  }

  return (
    <DialogShell shadeClick={pending ? undefined : onClose}>
      <header className="flex items-start justify-between border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>New Agent</div>
          <h2 className="m-0 text-xl font-semibold tracking-tight">Hire a headless Agent</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: "var(--ink-3)" }}>Start with the runtime. Add Slack, Telegram, Discord, or several connections afterward.</p>
        </div>
        <button type="button" className="af-btn af-btn-ghost af-btn-icon" disabled={pending} onClick={onClose}><XIcon /></button>
      </header>

      <div className="grid flex-1 gap-5 overflow-y-auto p-6 sm:grid-cols-2">
        <FormField label="Agent name">
          <input className="af-input" value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        </FormField>
        <FormField label="Runtime">
          <Select value={agentType} onValueChange={(value) => setAgentType(value as "openclaw" | "hermes")}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup><SelectItem value="hermes">Hermes</SelectItem><SelectItem value="openclaw">OpenClaw</SelectItem></SelectGroup></SelectContent>
          </Select>
        </FormField>
        <FormField label="Template" hint="Connections do not belong to templates or runtimes.">
          <Select value={templateKey} onValueChange={setTemplateKey} disabled={isLoading}>
            <SelectTrigger className="w-full"><SelectValue placeholder={isLoading ? "Loading templates…" : "Choose a template"} /></SelectTrigger>
            <SelectContent><SelectGroup>{templates.map((item) => <SelectItem key={`${item.templateKey}:${item.version}`} value={item.templateKey}>{item.templateName} · v{item.version}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </FormField>
        <FormField label="Model">
          <ModelSelect value={model} onChange={setModel} disabled={pending} />
        </FormField>
        <FormField label="Command approval">
          <Select value={approvalMode} onValueChange={(value) => setApprovalMode(value as "manual" | "auto" | "off")}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup><SelectItem value="auto">Automatic</SelectItem><SelectItem value="manual">Manual</SelectItem><SelectItem value="off">Off</SelectItem></SelectGroup></SelectContent>
          </Select>
        </FormField>
        <div className="rounded-xl border border-dashed p-4 text-sm" style={{ color: "var(--ink-3)" }}>
          Communication connections and integration credentials are configured independently after hiring.
        </div>
        {error && <p className="m-0 text-sm sm:col-span-2" style={{ color: "var(--err)" }}>{error}</p>}
      </div>

      <footer className="flex justify-end gap-2 border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
        <button type="button" className="af-btn" disabled={pending} onClick={onClose}>Cancel</button>
        <button type="button" className="af-btn af-btn-primary" disabled={pending || !template || !name.trim() || !model} onClick={() => void hire()}>
          {pending ? "Hiring…" : "Hire Agent"}
        </button>
      </footer>
    </DialogShell>
  );
}
