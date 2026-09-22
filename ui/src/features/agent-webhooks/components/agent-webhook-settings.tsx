"use client";

import { useState } from "react";
import { ChevronRight, CircleAlert, Copy, Plus, Trash2, Webhook as WebhookIcon } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Agent } from "@/features/agents/schemas";
import { AgentConfigurationSection } from "@/features/agents/components/agent-configuration-section";

import { useAgentWebhookActions, useAgentWebhooks, useWebhookDeliveryPlatforms } from "../hooks/use-agent-webhooks";
import type { AgentWebhook, WebhookDeliveryPlatform } from "../schemas";
import { WebhookDetail } from "./webhook-detail";

const PLATFORM_LABEL: Record<WebhookDeliveryPlatform, string> = {
  slack: "Slack",
  discord: "Discord",
  telegram: "Telegram",
  teams: "Microsoft Teams",
};

export function curlExample(url: string, secret: string): string {
  const body = '{"prompt":"Prepare a release summary."}';
  return [
    `SECRET='${secret}'`,
    `BODY='${body}'`,
    `SIGNATURE="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"`,
    "",
    `curl -X POST '${url}' \\`,
    `  -H 'X-AgentBarn-Webhook-Version: 1' \\`,
    `  -H "X-AgentBarn-Signature: $SIGNATURE" \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d "$BODY"`,
  ].join("\n");
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <button
      type="button"
      className="af-btn af-btn-sm"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard.writeText(value);
        toast.success("Copied to clipboard");
      }}
    >
      <Copy size={13} />
    </button>
  );
}

export function PayloadHint() {
  return (
    <p className="mt-2 text-xs text-[var(--ink-4)]">
      Only <code>prompt</code> is required, up to 5,000 characters. Add an optional <code>event_id</code> to make caller retries safe: a repeated{" "}
      <code>event_id</code> returns the original invocation instead of triggering the Agent again.
    </p>
  );
}

type Reveal = { webhook: AgentWebhook; secret: string };

export function AgentWebhookSettings({ agent, canEdit }: { agent: Agent; canEdit: boolean }) {
  const webhooks = useAgentWebhooks(agent.id);
  const platforms = useWebhookDeliveryPlatforms(agent.id);
  const { createWebhook, retireWebhook } = useAgentWebhookActions();
  const [selectedId, setSelectedId] = useQueryState(
    "webhook",
    parseAsString.withOptions({ history: "replace", scroll: false }),
  );
  const [adding, setAdding] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [deliveryPlatform, setDeliveryPlatform] = useState<WebhookDeliveryPlatform | "">("");
  const [formError, setFormError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<AgentWebhook | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);

  const selected = selectedId ? webhooks.data?.find((webhook) => webhook.id === selectedId) ?? null : null;
  const selectedPlatform = deliveryPlatform || platforms.data?.[0]?.key || "";

  async function addWebhook() {
    if (!selectedPlatform) return;
    try {
      const created = await createWebhook.mutateAsync({
        agentId: agent.id,
        displayName: displayName.trim(),
        deliveryPlatform: selectedPlatform,
      });
      setAdding(false);
      setDisplayName("");
      setDeliveryPlatform("");
      setFormError(null);
      if (created.signingSecret) setReveal({ webhook: created, secret: created.signingSecret });
      else void setSelectedId(created.id);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not create the webhook.");
    }
  }

  async function confirmRetire() {
    if (!retiring) return;
    await retireWebhook.mutateAsync({ agentId: agent.id, webhookId: retiring.id, revision: retiring.revision });
    setRetiring(null);
    if (selectedId === retiring.id) void setSelectedId(null);
  }

  return (
    <>
      {reveal ? (
        <SecretReveal
          reveal={reveal}
          onAcknowledge={() => {
            void setSelectedId(reveal.webhook.id);
            setReveal(null);
          }}
        />
      ) : selected ? (
        <WebhookDetail
          agent={agent}
          webhook={selected}
          platforms={platforms.data ?? []}
          canEdit={canEdit}
          onBack={() => void setSelectedId(null)}
          onSecretRotated={(webhook, secret) => setReveal({ webhook, secret })}
          onRetire={() => setRetiring(selected)}
        />
      ) : (
        <AgentConfigurationSection
          title="Webhooks"
          description="Signed URLs that submit one-shot jobs to this Agent. Results go to the selected native channel."
          footer={
            canEdit && !adding ? (
              <button type="button" className="af-btn af-btn-primary" onClick={() => setAdding(true)}>
                <Plus size={14} /> Add webhook
              </button>
            ) : undefined
          }
        >
          <div className="flex flex-col gap-3">
            {webhooks.isPending && <p className="m-0 text-sm text-[var(--ink-3)]">Loading webhooks…</p>}
            {webhooks.error && (
              <div className="flex items-center gap-2 text-sm text-[var(--err)]" role="alert">
                <CircleAlert size={15} /> Could not load webhooks.
                <button type="button" className="af-btn af-btn-sm" onClick={() => void webhooks.refetch()}>
                  Retry
                </button>
              </div>
            )}
            {!webhooks.isPending && !webhooks.error && webhooks.data?.length === 0 && !adding && (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--line-strong)] p-6 text-center">
                <WebhookIcon size={20} className="text-[var(--ink-4)]" />
                <p className="m-0 text-sm font-medium text-[var(--ink)]">No webhooks yet</p>
                <p className="m-0 max-w-md text-sm text-[var(--ink-3)]">
                  Connect a CI job, Jira automation, or another machine. Each webhook gets its own URL and signing secret.
                </p>
              </div>
            )}
            {webhooks.data?.map((webhook) => (
              <button
                key={webhook.id}
                type="button"
                className="af-card af-card-hover flex w-full items-center justify-between gap-3 p-4 text-left"
                onClick={() => void setSelectedId(webhook.id)}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <WebhookIcon size={14} className="text-[var(--accent-ink)]" />
                    <span className="truncate font-medium text-[var(--ink)]">{webhook.displayName}</span>
                    <span className="text-xs text-[var(--ink-4)]">{PLATFORM_LABEL[webhook.deliveryPlatform]}</span>
                  </div>
                  <div className="mt-1 truncate font-mono text-xs text-[var(--ink-4)]">{webhook.webhookUrl}</div>
                </div>
                <span className="text-xs text-[var(--ink-3)]">{webhook.enabled ? "Enabled" : "Disabled"}</span>
                <ChevronRight size={16} className="text-[var(--ink-4)]" />
              </button>
            ))}
            {adding && (
              <CreateWebhookForm
                displayName={displayName}
                platform={selectedPlatform}
                platforms={platforms.data ?? []}
                platformsLoading={platforms.isPending}
                error={formError}
                pending={createWebhook.isPending}
                onDisplayNameChange={setDisplayName}
                onPlatformChange={setDeliveryPlatform}
                onCancel={() => {
                  setAdding(false);
                  setFormError(null);
                }}
                onSubmit={() => void addWebhook()}
              />
            )}
          </div>
        </AgentConfigurationSection>
      )}

      <ConfirmationDialog
        open={retiring !== null}
        onOpenChange={(open) => !open && setRetiring(null)}
        title="Remove this webhook?"
        description={<>Removing <strong>{retiring?.displayName}</strong> immediately invalidates its URL.</>}
        confirmLabel="Remove webhook"
        pendingLabel="Removing…"
        variant="destructive"
        icon={<Trash2 size={18} />}
        isPending={retireWebhook.isPending}
        onConfirm={() => void confirmRetire()}
      />
    </>
  );
}

function CreateWebhookForm({ displayName, platform, platforms, platformsLoading, error, pending, onDisplayNameChange, onPlatformChange, onCancel, onSubmit }: {
  displayName: string;
  platform: WebhookDeliveryPlatform | "";
  platforms: { key: WebhookDeliveryPlatform; displayName: string }[];
  platformsLoading: boolean;
  error: string | null;
  pending: boolean;
  onDisplayNameChange: (value: string) => void;
  onPlatformChange: (value: WebhookDeliveryPlatform) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--line)] bg-[var(--bg-soft)] p-4">
      <label htmlFor="webhook-name" className="mb-1.5 block text-sm font-medium text-[var(--ink)]">Webhook name</label>
      <input id="webhook-name" className="af-input w-full" value={displayName} onChange={(event) => onDisplayNameChange(event.target.value)} placeholder="CI pipeline" autoFocus />
      <label htmlFor="webhook-platform" className="mb-1.5 mt-3 block text-sm font-medium text-[var(--ink)]">Deliver results to</label>
      <Select value={platform} onValueChange={(value) => onPlatformChange(value as WebhookDeliveryPlatform)} disabled={platformsLoading || platforms.length === 0}>
        <SelectTrigger id="webhook-platform" className="w-full"><SelectValue placeholder={platformsLoading ? "Loading channels…" : "Choose a channel"} /></SelectTrigger>
        <SelectContent><SelectGroup>{platforms.map((item) => <SelectItem key={item.key} value={item.key}>{PLATFORM_LABEL[item.key]} · {item.displayName}</SelectItem>)}</SelectGroup></SelectContent>
      </Select>
      {!platformsLoading && platforms.length === 0 && <p className="mt-2 text-xs text-[var(--err)]">Configure and enable Slack, Discord, Telegram, or Teams with a default channel before adding a webhook.</p>}
      <p className="mt-2 text-xs text-[var(--ink-4)]">For now, the runtime posts to that platform&apos;s configured default channel.</p>
      {error && <p className="mt-2 text-xs text-[var(--err)]" role="alert">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" className="af-btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="af-btn af-btn-primary" disabled={!displayName.trim() || !platform || pending} onClick={onSubmit}>{pending ? "Creating…" : "Create webhook"}</button>
      </div>
    </div>
  );
}

function SecretReveal({ reveal, onAcknowledge }: { reveal: Reveal; onAcknowledge: () => void }) {
  const url = reveal.webhook.webhookUrl ?? "";
  return (
    <AgentConfigurationSection title="Webhook secret" description="Shown once — copy it now." unstyled>
      <div className="af-card p-6">
        <h2 className="m-0 text-lg font-semibold text-[var(--ink)]">Signing secret ready</h2>
        <p className="mt-1 text-sm text-[var(--ink-3)]">This secret cannot be viewed again. Store it in the calling system.</p>
        {[["webhook-reveal-url", "Webhook URL", url], ["webhook-reveal-secret", "Signing secret", reveal.secret]].map(([id, label, value]) => (
          <div className="mt-4" key={id}>
            <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-[var(--ink)]">{label}</label>
            <div className="flex gap-1.5"><input id={id} readOnly value={value} className="af-input flex-1 font-mono text-xs" onFocus={(event) => event.currentTarget.select()} /><CopyButton value={value} label={`Copy ${label.toLowerCase()}`} /></div>
          </div>
        ))}
        <div className="mt-5 flex items-center justify-between"><span className="text-sm font-medium">Try it</span><CopyButton value={curlExample(url, reveal.secret)} label="Copy example request" /></div>
        <pre className="mt-1 overflow-x-auto rounded-lg bg-[var(--bg-soft)] p-3 text-xs text-[var(--ink-2)]">{curlExample(url, reveal.secret)}</pre>
        <PayloadHint />
        <div className="mt-6 flex justify-end"><button type="button" className="af-btn af-btn-primary" onClick={onAcknowledge}>I&apos;ve copied the secret</button></div>
      </div>
    </AgentConfigurationSection>
  );
}
