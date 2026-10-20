"use client";

import { XIcon } from "lucide-react";

import type { Agent } from "@/features/agents/schemas";

import { ConnectionForm } from "./connection-form";
import type { ConnectionDraft } from "./connection-drafts";

export function ConnectionIntegrations({ agent, drafts, onChange }: {
  agent: Agent;
  drafts: ConnectionDraft[];
  onChange: (drafts: ConnectionDraft[]) => void;
}) {
  return drafts.map((draft) => (
    <details key={draft.key} open={!draft.connection} className="p-4 rounded-2xl" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
      <summary className="flex cursor-pointer items-center justify-between">
        <span className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>Custom API{draft.value.name ? ` · ${draft.value.name}` : ""}</span>
        <button type="button" className="af-btn af-btn-ghost af-btn-icon" aria-label={`Remove Custom API${draft.value.name ? ` ${draft.value.name}` : ""}`} onClick={(event) => { event.preventDefault(); onChange(drafts.filter((item) => item.key !== draft.key)); }}><XIcon size={15} /></button>
      </summary>
      <div className="mt-3.5">
        <ConnectionForm agent={agent} prefix={`custom-api-${draft.key}`} connection={draft.connection} value={draft.value} onChange={(value) => onChange(drafts.map((item) => item.key === draft.key ? { ...item, value, changed: true } : item))} />
      </div>
    </details>
  ));
}
