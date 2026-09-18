"use client";

import { useState } from "react";
import { parseAsString, useQueryState } from "nuqs";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Webhook as WebhookIcon,
} from "lucide-react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  useCommunicationConnectionActions,
  useCommunicationConnectionCalls,
  useCommunicationConnections,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type { CommunicationCall, CommunicationConnection } from "@/features/communication-connections/schemas";
import { formatDate } from "@/shared/date";

import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";

/** Webhook has its own tab (AF-320 revision) — a machine caller is not messaging
 * anyone, and this is the one platform an Agent can hold several of. */
const WEBHOOK_PLATFORM_KEY = "webhook";

const STATUS_LABEL: Record<string, string> = {
  PENDING: "Waiting",
  PROCESSING: "Running",
  SUCCEEDED: "Succeeded",
  DEAD_LETTERED: "Failed",
  CANCELLED: "Cancelled",
  UNAVAILABLE: "Agent stopped",
};

function statusColor(status: string): string {
  switch (status) {
    case "SUCCEEDED":
      return "var(--ok)";
    case "DEAD_LETTERED":
      return "var(--err)";
    case "PROCESSING":
      return "var(--warn)";
    default:
      return "var(--ink-4)";
  }
}

function StatusDot({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: statusColor(status) }} />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** A ready-to-paste signed request, so this page doubles as the thing you test
 * the connection against. HMAC-SHA256 over the raw body, hex-encoded. */
function curlExample(url: string, secret: string): string {
  const body = '{"event_id":"evt-1","prompt":"Say hello and nothing else."}';
  return [
    `SECRET='${secret}'`,
    `BODY='${body}'`,
    `SIGNATURE="sha256=$(printf '%s' \"$BODY\" | openssl dgst -sha256 -hmac \"$SECRET\" | sed 's/^.* //')"`,
    "",
    `curl -X POST '${url}' \\`,
    `  -H 'X-AgentBarn-Webhook-Version: 1' \\`,
    `  -H "X-AgentBarn-Signature: $SIGNATURE" \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d "$BODY"`,
  ].join("\n");
}

function CopyButton({ value, label }: { value: string; label: string }) {
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

type Reveal = { mode: "create" | "regenerate"; connection: CommunicationConnection; secret: string };

export function AgentWebhookSettings({ agent, canEdit }: { agent: Agent; canEdit: boolean }) {
  const connections = useCommunicationConnections(agent.id);
  const webhooks = connections.data?.filter((connection) => connection.platformKey === WEBHOOK_PLATFORM_KEY) ?? [];
  const { createConnection, retireConnection } = useCommunicationConnectionActions();
  const [selectedId, setSelectedId] = useQueryState(
    "webhook",
    parseAsString.withOptions({ history: "replace", scroll: false }),
  );
  const [adding, setAdding] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<CommunicationConnection | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);

  const selected = selectedId ? webhooks.find((webhook) => webhook.id === selectedId) ?? null : null;

  async function addWebhook() {
    try {
      const created = await createConnection.mutateAsync({
        agentId: agent.id,
        platformKey: WEBHOOK_PLATFORM_KEY,
        displayName: displayName.trim(),
        enabled: true,
        settings: {},
        credentials: {},
      });
      setAdding(false);
      setDisplayName("");
      setFormError(null);
      const secret = created.credentialReveal?.signingSecret;
      if (secret) {
        setReveal({ mode: "create", connection: created, secret });
      } else {
        void setSelectedId(created.id);
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not create the webhook.");
    }
  }

  async function confirmRetire() {
    if (!retiring) return;
    await retireConnection.mutateAsync({ agentId: agent.id, connectionId: retiring.id, revision: retiring.revision });
    setRetiring(null);
    if (selectedId === retiring.id) void setSelectedId(null);
  }

  if (reveal) {
    return (
      <RevealPanel
        reveal={reveal}
        onAcknowledge={() => {
          if (reveal.mode === "create") void setSelectedId(reveal.connection.id);
          setReveal(null);
        }}
      />
    );
  }

  if (selected) {
    return (
      <WebhookDetail
        agent={agent}
        connection={selected}
        canEdit={canEdit}
        onBack={() => void setSelectedId(null)}
        onRegenerated={(connection, secret) => setReveal({ mode: "regenerate", connection, secret })}
        onRetire={() => setRetiring(selected)}
      />
    );
  }

  return (
    <>
      <AgentConfigurationSection
        title="Webhooks"
        description="URLs external systems can call to make this Agent run a job."
        footer={
          canEdit && !adding ? (
            <button type="button" className="af-btn af-btn-primary" onClick={() => setAdding(true)}>
              <Plus size={14} /> Add connection
            </button>
          ) : undefined
        }
      >
        <div className="flex flex-col gap-3">
          {connections.isPending && (
            <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>
              Loading webhooks…
            </p>
          )}
          {connections.error && (
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--err)" }}>
              <CircleAlert size={15} /> Could not load webhook connections.
            </div>
          )}
          {!connections.isPending && webhooks.length === 0 && !adding && (
            <div
              className="flex flex-col items-center gap-2 rounded-xl p-6 text-center"
              style={{ border: "1px dashed var(--line-strong)" }}
            >
              <WebhookIcon size={20} style={{ color: "var(--ink-4)" }} />
              <p className="m-0 text-sm font-medium" style={{ color: "var(--ink)" }}>
                No webhooks yet
              </p>
              <p className="m-0 max-w-sm text-sm" style={{ color: "var(--ink-3)" }}>
                A webhook gives an external system — Jira automation, a CI job, another Agent — its own URL
                and signing secret to make this Agent run a job. Add one to get started.
              </p>
            </div>
          )}
          {webhooks.map((webhook) => (
            <button
              key={webhook.id}
              type="button"
              className="af-card af-card-hover flex w-full items-center justify-between gap-3 p-4 text-left"
              onClick={() => void setSelectedId(webhook.id)}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="rounded-lg p-1.5" style={{ background: "var(--bg-elev)", color: "var(--accent-ink)" }}>
                    <WebhookIcon size={14} />
                  </span>
                  <span className="truncate font-medium" style={{ color: "var(--ink)" }}>
                    {webhook.displayName}
                  </span>
                </div>
                <div
                  className="mt-1 truncate text-xs"
                  style={{ color: "var(--ink-4)", fontFamily: "var(--font-mono, monospace)" }}
                >
                  {webhook.webhookUrl}
                </div>
              </div>
              <span className="flex-shrink-0 text-xs" style={{ color: webhook.enabled ? "var(--ink-3)" : "var(--ink-4)" }}>
                {webhook.enabled ? "Enabled" : "Disabled"}
              </span>
              <ChevronRight size={16} style={{ color: "var(--ink-4)" }} />
            </button>
          ))}

          {adding && (
            <div className="rounded-xl p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
              <label className="mb-1.5 block text-sm font-medium" style={{ color: "var(--ink)" }}>
                Connection name
              </label>
              <input
                className="af-input w-full"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Jira automation"
                autoFocus
              />
              <p className="mt-1.5 text-xs" style={{ color: "var(--ink-4)" }}>
                A URL and a signing secret are generated once you save. The secret is shown exactly once —
                copy it before you leave that screen.
              </p>
              {formError && (
                <p className="mt-2 text-xs" style={{ color: "var(--err)" }}>
                  {formError}
                </p>
              )}
              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  className="af-btn"
                  onClick={() => {
                    setAdding(false);
                    setDisplayName("");
                    setFormError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="af-btn af-btn-primary"
                  disabled={!displayName.trim() || createConnection.isPending}
                  onClick={() => void addWebhook()}
                >
                  {createConnection.isPending ? "Creating…" : "Create webhook"}
                </button>
              </div>
            </div>
          )}
        </div>
      </AgentConfigurationSection>

      <ConfirmationDialog
        open={retiring !== null}
        onOpenChange={(open) => !open && setRetiring(null)}
        title="Remove this webhook?"
        description={
          <>
            Removing <strong>{retiring?.displayName}</strong> immediately invalidates its URL. Any calling
            system still pointed at it starts failing.
          </>
        }
        confirmLabel="Remove webhook"
        pendingLabel="Removing…"
        variant="destructive"
        icon={<Trash2 size={18} />}
        isPending={retireConnection.isPending}
        onConfirm={() => void confirmRetire()}
      />
    </>
  );
}

function RevealPanel({ reveal, onAcknowledge }: { reveal: Reveal; onAcknowledge: () => void }) {
  const { connection, secret } = reveal;
  const url = connection.webhookUrl ?? "";
  return (
    <AgentConfigurationSection
      title="Webhook secret"
      description="Shown once — copy it now."
      unstyled
    >
      <div className="af-card p-6">
        <h2 className="m-0 text-lg font-semibold" style={{ color: "var(--ink)" }}>
          {reveal.mode === "create" ? "Webhook created" : "Signing secret regenerated"}
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--ink-3)" }}>
          This secret will not be shown again. Copy it now and give it to the calling system.
        </p>

        <div className="mt-5">
          <label className="mb-1.5 block text-sm font-medium" style={{ color: "var(--ink)" }}>
            Webhook URL
          </label>
          <div className="flex gap-1.5">
            <input readOnly value={url} className="af-input flex-1 text-xs" onFocus={(e) => e.currentTarget.select()} />
            <CopyButton value={url} label="Copy webhook URL" />
          </div>
        </div>

        <div className="mt-4">
          <label className="mb-1.5 block text-sm font-medium" style={{ color: "var(--ink)" }}>
            Signing secret
          </label>
          <div className="flex gap-1.5">
            <input
              readOnly
              value={secret}
              className="af-input flex-1 text-xs"
              style={{ fontFamily: "var(--font-mono, monospace)" }}
              onFocus={(e) => e.currentTarget.select()}
            />
            <CopyButton value={secret} label="Copy signing secret" />
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-1.5 flex items-center justify-between">
            <label className="text-sm font-medium" style={{ color: "var(--ink)" }}>
              Try it
            </label>
            <CopyButton value={curlExample(url, secret)} label="Copy example request" />
          </div>
          <pre
            className="overflow-x-auto rounded-lg p-3 text-xs"
            style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
          >
            {curlExample(url, secret)}
          </pre>
        </div>

        <div className="mt-6 flex justify-end">
          <button type="button" className="af-btn af-btn-primary" onClick={onAcknowledge}>
            I&apos;ve copied the secret
          </button>
        </div>
      </div>
    </AgentConfigurationSection>
  );
}

function WebhookDetail({
  agent,
  connection,
  canEdit,
  onBack,
  onRegenerated,
  onRetire,
}: {
  agent: Agent;
  connection: CommunicationConnection;
  canEdit: boolean;
  onBack: () => void;
  onRegenerated: (connection: CommunicationConnection, secret: string) => void;
  onRetire: () => void;
}) {
  const { updateConnection, rotateConnectionCredentials } = useCommunicationConnectionActions();
  const [editing, setEditing] = useState(false);
  const [editDisplayName, setEditDisplayName] = useState(connection.displayName);
  const [editHosts, setEditHosts] = useState(
    ((connection.settings.response_url_allowed_hosts as string[] | undefined) ?? []).join(", "),
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [regenerateOpen, setRegenerateOpen] = useState(false);

  function beginEditing() {
    setEditDisplayName(connection.displayName);
    setEditHosts(((connection.settings.response_url_allowed_hosts as string[] | undefined) ?? []).join(", "));
    setSaveError(null);
    setEditing(true);
  }

  async function saveEdits() {
    try {
      await updateConnection.mutateAsync({
        agentId: agent.id,
        connectionId: connection.id,
        revision: connection.revision,
        displayName: editDisplayName.trim(),
        settings: {
          response_url_allowed_hosts: editHosts
            .split(",")
            .map((host) => host.trim())
            .filter(Boolean),
        },
      });
      setEditing(false);
      setSaveError(null);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Could not save changes.");
    }
  }

  async function toggleEnabled() {
    await updateConnection.mutateAsync({
      agentId: agent.id,
      connectionId: connection.id,
      revision: connection.revision,
      enabled: !connection.enabled,
    });
  }

  async function confirmRegenerate() {
    const rotated = await rotateConnectionCredentials.mutateAsync({
      agentId: agent.id,
      connectionId: connection.id,
      revision: connection.revision,
    });
    setRegenerateOpen(false);
    const secret = rotated.credentialReveal?.signingSecret;
    if (secret) onRegenerated(rotated, secret);
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex w-fit items-center gap-1.5 rounded-lg px-2 py-1 text-[0.8125rem] transition-colors hover:bg-[var(--bg-soft)]"
        style={{ color: "var(--ink-3)" }}
      >
        <ArrowLeft size={14} /> Back to webhooks
      </button>

      <div className="af-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="rounded-lg p-1.5" style={{ background: "var(--bg-elev)", color: "var(--accent-ink)" }}>
                <WebhookIcon size={16} />
              </span>
              <h2 className="m-0 truncate text-lg font-semibold" style={{ color: "var(--ink)" }}>
                {connection.displayName}
              </h2>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs" style={{ color: "var(--ink-4)" }}>
              <span>{connection.enabled ? "Enabled" : "Disabled"}</span>
              <span aria-hidden>·</span>
              <span>Created {formatDate(connection.createdAt)}</span>
            </div>
          </div>
          {canEdit && (
            <div className="flex flex-shrink-0 flex-wrap gap-2">
              <button type="button" className="af-btn af-btn-sm" onClick={beginEditing}>
                <Pencil size={13} /> Edit
              </button>
              <button
                type="button"
                className="af-btn af-btn-sm"
                disabled={updateConnection.isPending}
                onClick={() => void toggleEnabled()}
              >
                {connection.enabled ? "Disable" : "Enable"}
              </button>
              <button type="button" className="af-btn af-btn-sm" onClick={() => setRegenerateOpen(true)}>
                <RefreshCw size={13} /> Regenerate secret
              </button>
              <button type="button" className="af-btn af-btn-sm" onClick={onRetire}>
                <Trash2 size={13} /> Remove
              </button>
            </div>
          )}
        </div>

        <div className="mt-4">
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>
            Webhook URL
          </label>
          <div className="flex gap-1.5">
            <input
              readOnly
              value={connection.webhookUrl ?? ""}
              className="af-input flex-1 text-xs"
              onFocus={(e) => e.currentTarget.select()}
            />
            <CopyButton value={connection.webhookUrl ?? ""} label="Copy webhook URL" />
          </div>
        </div>

        {agent.status === "RUNNING" && (
          <p className="mt-3 text-xs" style={{ color: "var(--ink-4)" }}>
            If this Agent was already running when a change was made here, restart it — a running Agent only
            picks up webhook changes after a restart.
          </p>
        )}

        {editing && (
          <div className="mt-4 rounded-lg p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <label className="mb-1.5 block text-sm font-medium" style={{ color: "var(--ink)" }}>
              Connection name
            </label>
            <input
              className="af-input w-full"
              value={editDisplayName}
              onChange={(event) => setEditDisplayName(event.target.value)}
            />
            <label className="mb-1.5 mt-3 block text-sm font-medium" style={{ color: "var(--ink)" }}>
              Hosts a reply may be sent to
            </label>
            <input
              className="af-input w-full"
              value={editHosts}
              onChange={(event) => setEditHosts(event.target.value)}
              placeholder="hooks.example.com, ci.example.com"
            />
            <p className="mt-1.5 text-xs" style={{ color: "var(--ink-4)" }}>
              Comma-separated hostnames. A reply is not sent yet — this is recorded now so the allowlist is a
              setup decision.
            </p>
            {saveError && (
              <p className="mt-2 text-xs" style={{ color: "var(--err)" }}>
                {saveError}
              </p>
            )}
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="af-btn" onClick={() => setEditing(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary"
                disabled={!editDisplayName.trim() || updateConnection.isPending}
                onClick={() => void saveEdits()}
              >
                {updateConnection.isPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        )}
      </div>

      <WebhookCalls agentId={agent.id} connectionId={connection.id} />

      <ConfirmationDialog
        open={regenerateOpen}
        onOpenChange={setRegenerateOpen}
        title="Regenerate the signing secret?"
        description="The URL stays the same. The old secret stops working immediately, so update the calling system with the new one."
        confirmLabel="Regenerate"
        pendingLabel="Regenerating…"
        icon={<RefreshCw size={18} />}
        isPending={rotateConnectionCredentials.isPending}
        onConfirm={() => void confirmRegenerate()}
      />
    </div>
  );
}

function WebhookCalls({ agentId, connectionId }: { agentId: string; connectionId: string }) {
  const { calls, total, isLoading, error, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useCommunicationConnectionCalls(agentId, connectionId);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="af-card p-5">
      <h3 className="m-0 text-sm font-semibold" style={{ color: "var(--ink)" }}>
        Calls {total > 0 && <span style={{ color: "var(--ink-4)", fontWeight: 400 }}>({total})</span>}
      </h3>
      <p className="mb-4 mt-1 text-xs" style={{ color: "var(--ink-4)" }}>
        Every request this webhook received and what the Agent sent back for it.
      </p>

      {isLoading && (
        <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>
          Loading calls…
        </p>
      )}
      {error && (
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--err)" }}>
          <CircleAlert size={15} /> Could not load this webhook&apos;s calls.
        </div>
      )}
      {!isLoading && calls.length === 0 && !error && (
        <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>
          No calls yet. Fire a signed request at the URL above to see it appear here.
        </p>
      )}

      <div className="flex flex-col divide-y" style={{ borderColor: "var(--line)" }}>
        {calls.map((call) => (
          <CallRow
            key={call.deliveryId}
            call={call}
            expanded={expandedId === call.deliveryId}
            onToggle={() => setExpandedId((current) => (current === call.deliveryId ? null : call.deliveryId))}
          />
        ))}
      </div>

      {hasNextPage && (
        <button
          type="button"
          className="af-btn af-btn-sm mt-3"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}

function CallRow({ call, expanded, onToggle }: { call: CommunicationCall; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="py-3">
      <button
        type="button"
        className="flex w-full items-start gap-2 text-left"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        {expanded ? (
          <ChevronDown size={15} className="mt-0.5 flex-shrink-0" style={{ color: "var(--ink-4)" }} />
        ) : (
          <ChevronRight size={15} className="mt-0.5 flex-shrink-0" style={{ color: "var(--ink-4)" }} />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs" style={{ color: "var(--ink-4)" }}>
            <span>{formatDate(call.occurredAt)}</span>
            <span aria-hidden>·</span>
            <StatusDot status={call.status} />
            <span aria-hidden>·</span>
            <code className="text-[0.7rem]">{call.eventId}</code>
          </div>
          <div className="mt-0.5 truncate text-sm" style={{ color: "var(--ink)" }}>
            {call.prompt}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="mt-3 ml-5.5 flex flex-col gap-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: "var(--ink-4)" }}>
            <span>Attempt {call.attemptCount}</span>
            {call.orderingKey && <span>Ordering key: {call.orderingKey}</span>}
            {call.completedAt && <span>Completed {formatDate(call.completedAt)}</span>}
          </div>
          <div>
            <div className="mb-1 text-xs font-medium" style={{ color: "var(--ink-3)" }}>
              Prompt received
            </div>
            <pre
              className="max-h-64 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap"
              style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
            >
              {call.prompt}
            </pre>
          </div>
          {call.lastErrorMessage && (
            <div className="flex items-start gap-2 rounded-lg p-3 text-xs" style={{ background: "var(--err-soft)", color: "var(--err)" }}>
              <CircleAlert size={14} className="mt-0.5 flex-shrink-0" />
              <span>
                {call.lastErrorCode && <strong>{call.lastErrorCode}: </strong>}
                {call.lastErrorMessage}
              </span>
            </div>
          )}
          <div>
            <div className="mb-1 text-xs font-medium" style={{ color: "var(--ink-3)" }}>
              Agent response
            </div>
            {call.responses.length === 0 ? (
              <p className="m-0 text-xs" style={{ color: "var(--ink-4)" }}>
                {call.status === "PENDING" || call.status === "PROCESSING" ? "No response yet." : "No response."}
              </p>
            ) : (
              call.responses.map((response, index) => (
                <pre
                  key={index}
                  className="mb-2 max-h-64 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap last:mb-0"
                  style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
                >
                  {response.text}
                </pre>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
