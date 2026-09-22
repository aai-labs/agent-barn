"use client";

import { useState } from "react";
import { ArrowLeft, Pencil, RefreshCw, Trash2, Webhook as WebhookIcon } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Agent } from "@/features/agents/schemas";
import { formatDate } from "@/shared/date";

import { useAgentWebhookActions } from "../hooks/use-agent-webhooks";
import type { AgentWebhook, WebhookDeliveryPlatform, WebhookDeliveryPlatformRead } from "../schemas";
import { deliveryPlatformOptionLabel, PLATFORM_LABEL } from "../utils";
import { CopyButton, PayloadHint } from "./agent-webhook-settings";
import { WebhookInvocationHistory } from "./webhook-invocation-history";

export function WebhookDetail({ agent, webhook, platforms, canEdit, onBack, onSecretRotated, onRetire }: {
  agent: Agent;
  webhook: AgentWebhook;
  platforms: WebhookDeliveryPlatformRead[];
  canEdit: boolean;
  onBack: () => void;
  onSecretRotated: (webhook: AgentWebhook, secret: string) => void;
  onRetire: () => void;
}) {
  const { updateWebhook, rotateSecret } = useAgentWebhookActions();
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(webhook.displayName);
  const [deliveryPlatform, setDeliveryPlatform] = useState(webhook.deliveryPlatform);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [rotateOpen, setRotateOpen] = useState(false);

  async function save() {
    try {
      await updateWebhook.mutateAsync({ agentId: agent.id, webhookId: webhook.id, revision: webhook.revision, displayName: displayName.trim(), deliveryPlatform });
      setEditing(false);
      setSaveError(null);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not save changes.");
    }
  }

  async function toggleEnabled() {
    await updateWebhook.mutateAsync({ agentId: agent.id, webhookId: webhook.id, revision: webhook.revision, enabled: !webhook.enabled });
  }

  async function confirmRotate() {
    const rotated = await rotateSecret.mutateAsync({ agentId: agent.id, webhookId: webhook.id, revision: webhook.revision });
    setRotateOpen(false);
    if (rotated.signingSecret) onSecretRotated(rotated, rotated.signingSecret);
  }

  return (
    <div className="flex flex-col gap-4">
      <button type="button" onClick={onBack} className="inline-flex w-fit items-center gap-1.5 rounded-lg px-2 py-1 text-[0.8125rem] text-[var(--ink-3)] transition-colors hover:bg-[var(--bg-soft)]"><ArrowLeft size={14} /> Back to webhooks</button>
      <div className="af-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2"><WebhookIcon size={16} className="text-[var(--accent-ink)]" /><h2 className="m-0 truncate text-lg font-semibold text-[var(--ink)]">{webhook.displayName}</h2></div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-[var(--ink-4)]"><span>{webhook.enabled ? "Enabled" : "Disabled"}</span><span aria-hidden>·</span><span>{PLATFORM_LABEL[webhook.deliveryPlatform]}</span><span aria-hidden>·</span><span>Created {formatDate(webhook.createdAt)}</span></div>
          </div>
          {canEdit && <div className="flex flex-wrap gap-2"><button type="button" className="af-btn af-btn-sm" onClick={() => setEditing(true)}><Pencil size={13} /> Edit</button><button type="button" className="af-btn af-btn-sm" disabled={updateWebhook.isPending} onClick={() => void toggleEnabled()}>{webhook.enabled ? "Disable" : "Enable"}</button><button type="button" className="af-btn af-btn-sm" onClick={() => setRotateOpen(true)}><RefreshCw size={13} /> Rotate secret</button><button type="button" className="af-btn af-btn-sm" onClick={onRetire}><Trash2 size={13} /> Remove</button></div>}
        </div>
        <div className="mt-4">
          <label htmlFor="webhook-detail-url" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[var(--ink-4)]">Webhook URL</label>
          <div className="flex gap-1.5"><input id="webhook-detail-url" readOnly value={webhook.webhookUrl ?? ""} className="af-input flex-1 font-mono text-xs" onFocus={(event) => event.currentTarget.select()} /><CopyButton value={webhook.webhookUrl ?? ""} label="Copy webhook URL" /></div>
          <PayloadHint />
        </div>
        <p className="mt-3 text-xs text-[var(--ink-4)]">The native runtime posts the final result to this platform&apos;s configured default channel. Agent Barn does not receive or store that result.</p>
        {editing && <div className="mt-4 rounded-lg border border-[var(--line)] bg-[var(--bg-soft)] p-4">
          <label htmlFor="edit-webhook-name" className="mb-1.5 block text-sm font-medium">Webhook name</label>
          <input id="edit-webhook-name" className="af-input w-full" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          <label htmlFor="edit-webhook-platform" className="mb-1.5 mt-3 block text-sm font-medium">Deliver results to</label>
          <Select value={deliveryPlatform} onValueChange={(value) => setDeliveryPlatform(value as WebhookDeliveryPlatform)}><SelectTrigger id="edit-webhook-platform" className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectGroup>{platforms.map((item) => <SelectItem key={item.key} value={item.key}>{deliveryPlatformOptionLabel(item)}</SelectItem>)}</SelectGroup></SelectContent></Select>
          {saveError && <p className="mt-2 text-xs text-[var(--err)]" role="alert">{saveError}</p>}
          <div className="mt-3 flex justify-end gap-2"><button type="button" className="af-btn" onClick={() => setEditing(false)}>Cancel</button><button type="button" className="af-btn af-btn-primary" disabled={!displayName.trim() || updateWebhook.isPending} onClick={() => void save()}>{updateWebhook.isPending ? "Saving…" : "Save changes"}</button></div>
        </div>}
      </div>
      <WebhookInvocationHistory agentId={agent.id} webhookId={webhook.id} canRetry={canEdit} />
      <ConfirmationDialog open={rotateOpen} onOpenChange={setRotateOpen} title="Rotate the signing secret?" description="The URL stays the same, but the old secret stops working immediately." confirmLabel="Rotate secret" pendingLabel="Rotating…" icon={<RefreshCw size={18} />} isPending={rotateSecret.isPending} onConfirm={() => void confirmRotate()} />
    </div>
  );
}
