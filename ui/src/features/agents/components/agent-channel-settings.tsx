"use client";

import { useMemo, useState } from "react";
import { Cable, CircleAlert, Plus, Trash2 } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  useCommunicationConnectionActions,
  useCommunicationConnections,
  useCommunicationPlatforms,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type { CommunicationConnection } from "@/features/communication-connections/schemas";

import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";

function schemaDefaults(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return {};
  return Object.fromEntries(
    Object.entries(properties).flatMap(([key, value]) => {
      if (!value || typeof value !== "object" || Array.isArray(value) || !("default" in value)) return [];
      return [[key, (value as { default: unknown }).default]];
    }),
  );
}

type SchemaProperty = {
  title?: string;
  type?: string;
  default?: unknown;
  pattern?: string;
  items?: { type?: string };
};

function schemaProperties(schema: Record<string, unknown>): Array<[string, SchemaProperty]> {
  if (!schema.properties || typeof schema.properties !== "object" || Array.isArray(schema.properties)) return [];
  return Object.entries(schema.properties).filter(
    (entry): entry is [string, SchemaProperty] => Boolean(entry[1]) && typeof entry[1] === "object" && !Array.isArray(entry[1]),
  );
}

function patternOptions(pattern?: string): string[] {
  const match = pattern?.match(/^\^\(([^)]+)\)\$$/);
  return match?.[1]?.split("|") ?? [];
}

function SchemaFields({
  schema,
  values,
  onChange,
  secret = false,
}: {
  schema: Record<string, unknown>;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  secret?: boolean;
}) {
  const required = new Set(Array.isArray(schema.required) ? schema.required.filter((item): item is string => typeof item === "string") : []);
  return schemaProperties(schema).map(([key, property]) => {
    const label = property.title ?? key.replaceAll("_", " ");
    const value = values[key] ?? property.default ?? (property.type === "array" ? [] : property.type === "boolean" ? false : "");
    const choices = patternOptions(property.pattern);
    const update = (next: unknown) => onChange({ ...values, [key]: next });

    if (property.type === "boolean") {
      return (
        <label key={key} className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={Boolean(value)} onChange={(event) => update(event.target.checked)} />
          {label}
        </label>
      );
    }
    if (choices.length > 0) {
      return (
        <label key={key} className="flex flex-col gap-1.5 text-sm font-medium">
          {label}{required.has(key) ? " *" : ""}
          <Select value={String(value)} onValueChange={update}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup>{choices.map((choice) => <SelectItem key={choice} value={choice}>{choice}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </label>
      );
    }
    return (
      <label key={key} className="flex flex-col gap-1.5 text-sm font-medium">
        {label}{required.has(key) ? " *" : ""}
        <input
          className="af-input"
          type={secret ? "password" : "text"}
          autoComplete={secret ? "new-password" : undefined}
          value={Array.isArray(value) ? value.join(", ") : String(value)}
          placeholder={property.type === "array" ? "Comma-separated values" : undefined}
          onChange={(event) => update(property.type === "array"
            ? event.target.value.split(",").map((item) => item.trim()).filter(Boolean)
            : event.target.value)}
        />
      </label>
    );
  });
}

function statusLabel(connection: CommunicationConnection): string {
  if (!connection.enabled) return "Disabled";
  return connection.observedStatus?.replaceAll("_", " ") ?? "Pending";
}

export function AgentChannelSettings({
  agent,
  canEdit,
}: {
  agent: Agent;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const connections = useCommunicationConnections(agent.id);
  const platforms = useCommunicationPlatforms();
  const { createConnection, updateConnection, retireConnection } = useCommunicationConnectionActions();
  const [adding, setAdding] = useState(false);
  const [platformKey, setPlatformKey] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [credentials, setCredentials] = useState<Record<string, unknown>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<CommunicationConnection | null>(null);

  const selectedPlatform = useMemo(
    () => platforms.data?.find((platform) => platform.key === platformKey),
    [platformKey, platforms.data],
  );

  function choosePlatform(key: string) {
    const platform = platforms.data?.find((candidate) => candidate.key === key);
    setPlatformKey(key);
    setDisplayName(platform?.displayName ?? key);
    setSettings(schemaDefaults(platform?.settingsSchema ?? {}));
    setCredentials(schemaDefaults(platform?.credentialsSchema ?? {}));
    setFormError(null);
  }

  async function addConnection() {
    try {
      await createConnection.mutateAsync({
        agentId: agent.id,
        platformKey,
        displayName: displayName.trim(),
        enabled: true,
        settings,
        credentials,
      });
      setAdding(false);
      setPlatformKey("");
      setDisplayName("");
      setSettings({});
      setCredentials({});
      setFormError(null);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not create the connection.");
    }
  }

  return (
    <AgentConfigurationSection
      title="Communication connections"
      description="Attach any number of provider connections. The Agent runtime remains provider-independent."
      footer={canEdit && !adding ? (
        <button type="button" className="af-btn af-btn-primary" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add connection
        </button>
      ) : undefined}
    >
      <div className="flex flex-col gap-4">
        {connections.isPending && <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>Loading connections…</p>}
        {connections.error && (
          <div className="flex items-center gap-2 text-sm" style={{ color: "var(--err)" }}>
            <CircleAlert size={15} /> Could not load communication connections.
          </div>
        )}
        {connections.data?.map((connection) => (
          <div key={connection.id} className="rounded-xl p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 rounded-lg p-2" style={{ background: "var(--bg-elev)", color: "var(--accent-ink)" }}><Cable size={16} /></span>
                <div className="min-w-0">
                  <div className="font-medium" style={{ color: "var(--ink)" }}>{connection.displayName}</div>
                  <div className="mt-0.5 text-xs" style={{ color: "var(--ink-4)" }}>
                    {connection.platformKey} · {connection.externalIdentity ?? "identity pending"} · {statusLabel(connection)}
                  </div>
                  {connection.lastErrorMessage && <div className="mt-2 text-xs" style={{ color: "var(--err)" }}>{connection.lastErrorMessage}</div>}
                  {connection.webhookUrl && (
                    <div className="mt-2 text-xs" style={{ color: "var(--ink-3)" }}>
                      Configure the provider webhook as <code className="break-all">{connection.webhookUrl}</code>
                    </div>
                  )}
                </div>
              </div>
              {canEdit && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="af-btn af-btn-sm"
                    disabled={updateConnection.isPending}
                    onClick={() => void updateConnection.mutateAsync({
                      agentId: agent.id,
                      connectionId: connection.id,
                      revision: connection.revision,
                      enabled: !connection.enabled,
                    })}
                  >
                    {connection.enabled ? "Disable" : "Enable"}
                  </button>
                  <button type="button" className="af-btn af-btn-sm" aria-label={`Remove ${connection.displayName}`} onClick={() => setRetiring(connection)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {!connections.isPending && connections.data?.length === 0 && !adding && (
          <div className="rounded-xl border border-dashed p-6 text-center">
            <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>This Agent is headless. Add one or more connections when you want people to message it.</p>
          </div>
        )}

        {adding && (
          <div className="flex flex-col gap-4 rounded-xl p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div>
              <h3 className="m-0 text-sm font-semibold">New connection</h3>
              <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-3)" }}>The installed plugin validates and encrypts this configuration. Credentials are never returned by the API.</p>
            </div>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Platform
              <Select value={platformKey} onValueChange={choosePlatform}>
                <SelectTrigger className="w-full"><SelectValue placeholder="Choose a platform" /></SelectTrigger>
                <SelectContent><SelectGroup>{platforms.data?.map((platform) => <SelectItem key={platform.key} value={platform.key}>{platform.displayName}</SelectItem>)}</SelectGroup></SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Connection name
              <input className="af-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Customer support Slack" />
            </label>
            {selectedPlatform && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <SchemaFields schema={selectedPlatform.settingsSchema} values={settings} onChange={setSettings} />
                </div>
                <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)" }}>
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>Credentials</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <SchemaFields schema={selectedPlatform.credentialsSchema} values={credentials} onChange={setCredentials} secret />
                  </div>
                </div>
              </>
            )}
            {(formError || createConnection.error) && <p className="m-0 text-xs" style={{ color: "var(--err)" }}>{formError ?? "Could not create the connection."}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="af-btn" onClick={() => { setAdding(false); setFormError(null); }}>Cancel</button>
              <button type="button" className="af-btn af-btn-primary" disabled={!platformKey || !displayName.trim() || createConnection.isPending} onClick={() => void addConnection()}>{createConnection.isPending ? "Connecting…" : "Create connection"}</button>
            </div>
          </div>
        )}
      </div>

      <ConfirmationDialog
        open={Boolean(retiring)}
        onOpenChange={(open) => { if (!open) setRetiring(null); }}
        title="Remove this communication connection?"
        description="Pending deliveries are cancelled, credentials are scrubbed, and conversation history is preserved."
        confirmLabel="Remove connection"
        pendingLabel="Removing…"
        variant="destructive"
        isPending={retireConnection.isPending}
        onConfirm={async () => {
          if (!retiring) return;
          await retireConnection.mutateAsync({ agentId: agent.id, connectionId: retiring.id, revision: retiring.revision });
          setRetiring(null);
        }}
      />
    </AgentConfigurationSection>
  );
}
