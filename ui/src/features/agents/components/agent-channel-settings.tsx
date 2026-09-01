"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Check,
  CircleAlert,
  Copy,
  Info,
  LockKeyhole,
  MessageCircleWarning,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { EyeIcon, EyeOffIcon } from "@/components/icons";
import { platformIcon } from "@/components/brand-icons";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  useCommunicationConnectionActions,
  useCommunicationConnections,
  useCommunicationConnectionDirectory,
  useCommunicationPlatforms,
  useDownloadAppPackage,
} from "@/features/communication-connections/hooks/use-communication-connections";
import type { CommunicationConnection, CommunicationDirectoryEntry } from "@/features/communication-connections/schemas";

import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";

function titleCase(text: string): string {
  return text.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Small colored dot + text, matching the status language used across the agent list/detail views. */
function StatusDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function connectionStatus(connection: CommunicationConnection): { color: string; label: string } {
  if (!connection.enabled) return { color: "var(--ink-4)", label: "Disabled" };
  switch (connection.observedStatus) {
    case "CONNECTED": return { color: "var(--ok)", label: "Connected" };
    case "DEGRADED": return { color: "var(--warn)", label: "Degraded" };
    case "ERROR": return { color: "var(--err)", label: "Error" };
    case "CONNECTING": return { color: "var(--warn)", label: "Connecting…" };
    case "PENDING":
    default: return { color: "var(--ink-4)", label: "Waiting to connect" };
  }
}

/** Platform icon for a connection, falling back to a generic glyph for platforms without a brand icon yet. */
function ConnectionIcon({ platformKey, size = 16 }: { platformKey: string; size?: number }) {
  return platformIcon(platformKey, { size }) ?? <Plug size={size} />;
}

function PlatformSetupHint({
  hint,
  manifest,
  title = "Setup requirements",
}: {
  hint?: string | null;
  manifest?: Record<string, unknown> | null;
  title?: string;
}) {
  if (!hint && !manifest) return null;
  return (
    <div
      className="flex items-start gap-2.5 rounded-xl p-3.5"
      style={{
        border: "1px solid color-mix(in srgb, var(--accent) 30%, transparent)",
        background: "var(--accent-soft)",
      }}
    >
      <Info size={16} className="mt-0.5 flex-shrink-0" style={{ color: "var(--accent-ink)" }} />
      <div>
        <div className="text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--accent-ink)" }}>
          {title}
        </div>
        <p
          className="mb-0 mt-1 text-xs leading-relaxed"
          style={{ color: "var(--ink-2)", whiteSpace: "pre-line" }}
        >
          {hint}
        </p>
        {manifest && (
          <button
            type="button"
            className="af-btn af-btn-sm mt-3"
            onClick={() => void navigator.clipboard.writeText(JSON.stringify(manifest, null, 2)).then(() => toast.success("Slack manifest copied"))}
          >
            <Copy size={14} /> Copy Slack manifest
          </button>
        )}
      </div>
    </div>
  );
}

function PlatformOption({
  platform,
  selected,
  onSelect,
}: {
  platform: { key: string; displayName: string };
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`Select ${platform.displayName}`}
      className="group flex min-h-[4.75rem] cursor-pointer items-center gap-3 rounded-xl p-3 text-left transition-colors hover:shadow-sm"
      style={{
        border: selected ? "1.5px solid var(--accent)" : "1px solid var(--line)",
        background: selected ? "var(--accent-soft)" : "var(--bg-elev)",
        color: "var(--ink)",
      }}
      onClick={onSelect}
    >
      <span
        className="grid h-10 w-10 flex-shrink-0 place-items-center rounded-lg transition-colors"
        style={{ background: selected ? "var(--bg-elev)" : "var(--bg-soft)" }}
      >
        <ConnectionIcon platformKey={platform.key} size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{platform.displayName}</span>
        <span className="mt-0.5 block text-xs" style={{ color: "var(--ink-3)" }}>
          {selected ? "Selected" : "Connect a channel"}
        </span>
      </span>
      <span
        className="grid h-5 w-5 flex-shrink-0 place-items-center rounded-full"
        style={selected
          ? { background: "var(--accent-ink)", color: "var(--bg-elev)" }
          : { border: "1px solid var(--line-strong)", color: "transparent" }}
      >
        <Check size={12} strokeWidth={3} />
      </span>
    </button>
  );
}

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
  description?: string;
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

function SchemaArrayInput({
  label,
  value,
  onChange,
  suggestions = [],
}: {
  label: string;
  value: unknown;
  onChange: (value: string[]) => void;
  suggestions?: CommunicationDirectoryEntry[];
}) {
  const values = Array.isArray(value) ? value.map(String) : [];
  const [draft, setDraft] = useState("");
  const commit = (next: string) => {
    const additions = next.split(",").map((item) => item.trim()).filter(Boolean);
    if (additions.length) onChange([...values, ...additions.filter((item) => !values.includes(item))]);
    setDraft("");
  };
  const remove = (item: string) => onChange(values.filter((valueItem) => valueItem !== item));

  return (
    <div className="rounded-md border p-2" style={{ borderColor: "var(--line)", background: "var(--bg-elev)" }}>
      {values.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {values.map((item) => {
            const suggestion = suggestions.find((candidate) => candidate.id === item);
            return <span key={item} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}>
              {suggestion?.label ?? item}
              <button type="button" aria-label={`Remove ${suggestion?.label ?? item}`} className="cursor-pointer" onClick={() => remove(item)}>×</button>
            </span>;
          })}
        </div>
      )}
      <input
        className="af-input w-full border-0 p-0 shadow-none focus-visible:ring-0"
        aria-label={label}
        value={draft}
        placeholder="Type a value, then press Enter or comma"
        onChange={(event) => {
          const next = event.target.value;
          if (next.includes(",")) {
            const segments = next.split(",");
            commit(segments.slice(0, -1).join(","));
            setDraft(segments.at(-1) ?? "");
          } else setDraft(next);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") { event.preventDefault(); commit(draft); }
          if (event.key === "Backspace" && !draft && values.length) remove(values.at(-1) ?? "");
        }}
        onBlur={() => commit(draft)}
      />
      {suggestions.length > 0 && (
        <div className="mt-2 flex max-h-28 flex-wrap gap-1 overflow-y-auto">
          {suggestions.filter((candidate) => !values.includes(candidate.id)).map((candidate) => (
            <button key={candidate.id} type="button" className="rounded px-1.5 py-0.5 text-xs hover:bg-[var(--bg-soft)]" style={{ color: "var(--ink-3)" }} onClick={() => onChange([...values, candidate.id])}>
              {candidate.label}{candidate.detail ? ` · ${candidate.detail}` : ""}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SchemaTextInput({
  label,
  property,
  value,
  onChange,
  secret,
  suggestions,
}: {
  label: string;
  property: SchemaProperty;
  value: unknown;
  onChange: (value: unknown) => void;
  secret: boolean;
  suggestions?: CommunicationDirectoryEntry[];
}) {
  const [visible, setVisible] = useState(false);
  if (property.type === "array") {
    return <SchemaArrayInput label={label} value={value} onChange={(next) => onChange(next)} suggestions={suggestions} />;
  }

  return (
    <div className="relative w-full">
      <input
        className={secret ? "af-input w-full pr-10" : "af-input w-full"}
        type={secret && !visible ? "password" : "text"}
        autoComplete={secret ? "new-password" : undefined}
        spellCheck={false}
        value={String(value)}
        onChange={(event) => onChange(event.target.value)}
      />
      {secret && (
        <button
          type="button"
          className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer rounded-md p-1 transition-colors hover:bg-[var(--bg-soft)]"
          style={{ color: "var(--ink-4)" }}
          aria-label={visible ? `Hide ${label}` : `Show ${label}`}
          title={visible ? "Hide value" : "Show value"}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
        </button>
      )}
    </div>
  );
}

function SchemaFields({
  schema,
  values,
  onChange,
  secret = false,
  arraySuggestions = {},
}: {
  schema: Record<string, unknown>;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  secret?: boolean;
  arraySuggestions?: Record<string, CommunicationDirectoryEntry[]>;
}) {
  const required = new Set(Array.isArray(schema.required) ? schema.required.filter((item): item is string => typeof item === "string") : []);
  return schemaProperties(schema).map(([key, property]) => {
    const label = property.title ?? titleCase(key);
    const value = values[key] ?? property.default ?? (property.type === "array" ? [] : property.type === "boolean" ? false : "");
    const choices = patternOptions(property.pattern);
    const update = (next: unknown) => onChange({ ...values, [key]: next });
    const hint = property.description && (
      <span className="text-xs" style={{ color: "var(--ink-4)" }}>{property.description}</span>
    );

    if (property.type === "boolean") {
      return (
        <label key={key} className="flex flex-col gap-1">
          <span className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={Boolean(value)} onChange={(event) => update(event.target.checked)} />
            {label}
          </span>
          {hint}
        </label>
      );
    }
    if (choices.length > 0) {
      return (
        <label key={key} className="flex flex-col gap-1.5 text-sm font-medium">
          {label}{required.has(key) ? " *" : ""}
          <Select value={String(value)} onValueChange={update}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup>{choices.map((choice) => <SelectItem key={choice} value={choice}>{titleCase(choice)}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
          {hint}
        </label>
      );
    }
    return (
      <label key={key} className="flex w-full flex-col gap-1.5 text-sm font-medium">
        {label}{required.has(key) ? " *" : ""}
        <SchemaTextInput label={label} property={property} value={value} onChange={update} secret={secret} suggestions={arraySuggestions[key]} />
        {hint}
      </label>
    );
  });
}

export function AgentChannelSettings({
  agent,
  canEdit,
  autoOpen = false,
}: {
  agent: Agent;
  canEdit: boolean;
  /** Open the add-connection form immediately — used when arriving here via the
   * "Add a connection" shortcut on the Agent page, so there's no extra click to find. */
  autoOpen?: boolean;
}) {
  const connections = useCommunicationConnections(agent.id);
  const platforms = useCommunicationPlatforms();
  const { createConnection, updateConnection, retireConnection } = useCommunicationConnectionActions();
  const [adding, setAdding] = useState(autoOpen && canEdit);
  const [platformKey, setPlatformKey] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [credentials, setCredentials] = useState<Record<string, unknown>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<CommunicationConnection | null>(null);
  const downloadAppPackage = useDownloadAppPackage();
  const [packageBusyId, setPackageBusyId] = useState<string | null>(null);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [editingConnection, setEditingConnection] = useState<CommunicationConnection | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editSettings, setEditSettings] = useState<Record<string, unknown>>({});
  const [editCredentials, setEditCredentials] = useState<Record<string, unknown>>({});
  const editingSlack = editingConnection?.platformKey === "slack";
  const editingDiscord = editingConnection?.platformKey === "discord";
  const [discordGuildId, setDiscordGuildId] = useState("");
  const slackChannels = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "channels", "", editingSlack);
  const slackUsers = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "users", "", editingSlack);
  const discordGuilds = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "guilds", "", editingDiscord);
  const discordChannels = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "channels", "", editingDiscord && Boolean(discordGuildId), discordGuildId);
  const discordUsers = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "users", "", editingDiscord && Boolean(discordGuildId), discordGuildId);
  const discordRoles = useCommunicationConnectionDirectory(agent.id, editingConnection?.id ?? "", "roles", "", editingDiscord && Boolean(discordGuildId), discordGuildId);

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

  function beginEditing(connection: CommunicationConnection) {
    setEditingConnection(connection);
    setEditDisplayName(connection.displayName);
    setEditSettings(connection.settings);
    setEditCredentials({});
    setDiscordGuildId("");
    setFormError(null);
  }

  async function saveConnection() {
    if (!editingConnection) return;
    const credentialsChanged = Object.values(editCredentials).some(
      (value) => Array.isArray(value) ? value.length > 0 : value !== "" && value !== null && value !== undefined,
    );
    try {
      await updateConnection.mutateAsync({
        agentId: agent.id,
        connectionId: editingConnection.id,
        revision: editingConnection.revision,
        displayName: editDisplayName.trim(),
        settings: editSettings,
        ...(credentialsChanged ? { credentials: editCredentials } : {}),
      });
      setEditingConnection(null);
      setEditCredentials({});
      setFormError(null);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not update the connection.");
    }
  }

  return (
    <AgentConfigurationSection
      title="Messaging connections"
      description="Connect a messaging platform so people can message this Agent. Add as many as you like."
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
            <div className="flex flex-col gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 rounded-lg p-2" style={{ background: "var(--bg-elev)", color: "var(--accent-ink)" }}>
                  <ConnectionIcon platformKey={connection.platformKey} />
                </span>
                <div className="min-w-0">
                  <div className="font-medium" style={{ color: "var(--ink)" }}>{connection.displayName}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs" style={{ color: "var(--ink-4)" }}>
                    <span>{connection.externalIdentity ? `Connected as ${connection.externalIdentity}` : "Not connected yet"}</span>
                    <span aria-hidden>·</span>
                    <span>Provider:</span>
                    <StatusDot {...connectionStatus(connection)} />
                  </div>
                  {connection.lastErrorMessage && (
                    <div
                      className="mt-3 flex w-full max-w-none items-start gap-2 rounded-lg px-2.5 py-2"
                      role="alert"
                      style={{
                        border: "1px solid color-mix(in srgb, var(--err) 24%, var(--line))",
                        background: "color-mix(in srgb, var(--err) 6%, var(--bg-elev))",
                      }}
                    >
                      <CircleAlert size={14} className="mt-0.5 flex-shrink-0" style={{ color: "var(--err)" }} />
                      <div className="min-w-0 flex-1 text-xs">
                        <div className="font-medium" style={{ color: "var(--ink-2)" }}>
                          Latest provider error{connection.lastErrorCode ? ` · ${connection.lastErrorCode}` : ""}
                        </div>
                        <p
                          className="mb-0 mt-0.5 break-words whitespace-pre-wrap leading-relaxed"
                          style={{ color: "var(--ink-3)" }}
                        >
                          {connection.lastErrorMessage}
                        </p>
                        {connection.lastErrorDetails && (
                          <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[11px]" style={{ color: "var(--ink-4)" }}>
                            <span>{connection.lastErrorDetails.category.replace(/_/g, " ")}</span>
                            {connection.lastErrorDetails.httpStatus !== null && (
                              <span>HTTP {connection.lastErrorDetails.httpStatus}</span>
                            )}
                            {connection.lastErrorDetails.providerCode && (
                              <span>Provider code: {connection.lastErrorDetails.providerCode}</span>
                            )}
                            {connection.lastErrorDetails.retryable && <span>Retryable</span>}
                            {connection.lastErrorDetails.requestId && (
                              <span>Request ID: {connection.lastErrorDetails.requestId}</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {connection.webhookUrl && (
                    <div className="mt-2 text-xs" style={{ color: "var(--ink-3)" }}>
                      Paste this URL into {platforms.data?.find((p) => p.key === connection.platformKey)?.displayName ?? "the platform"}&apos;s webhook settings: <code className="break-all">{connection.webhookUrl}</code>
                    </div>
                  )}
                  {platforms.data
                    ?.find((p) => p.key === connection.platformKey)
                    ?.capabilities.includes("application_provisioning") && (
                    <div className="mt-2 flex items-center gap-2 text-xs" style={{ color: "var(--ink-3)" }}>
                      <span>Install the app in your workspace to add this Agent to channels and chats.</span>
                      <button
                        type="button"
                        className="af-btn af-btn-sm flex-shrink-0"
                        disabled={packageBusyId === connection.id}
                        onClick={() => {
                          setPackageBusyId(connection.id);
                          setPackageError(null);
                          void downloadAppPackage(agent.id, connection.id, connection.displayName)
                            .catch((cause: unknown) =>
                              setPackageError(
                                cause instanceof Error ? cause.message : "Could not build the app package.",
                              ),
                            )
                            .finally(() => setPackageBusyId(null));
                        }}
                      >
                        {packageBusyId === connection.id ? "Preparing…" : "Download app package"}
                      </button>
                    </div>
                  )}
                  {packageError && packageBusyId === null && (
                    <div className="mt-2 text-xs" style={{ color: "var(--err)" }}>{packageError}</div>
                  )}
                  <div className="mt-3">
                    <PlatformSetupHint
                      hint={platforms.data?.find((p) => p.key === connection.platformKey)?.postSetupHint}
                      title="Finish setup"
                    />
                  </div>
                </div>
              </div>
              <div className="flex w-full flex-wrap gap-2">
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  aria-label={`Refresh status for ${connection.displayName}`}
                  disabled={connections.isFetching}
                  onClick={() => void connections.refetch()}
                >
                  <RefreshCw size={14} className={connections.isFetching ? "animate-spin" : undefined} /> Refresh status
                </button>
                <Link
                  href={`/dashboard/${agent.organizationId}/agents/${agent.id}/connections/${connection.id}`}
                  className="af-btn af-btn-sm"
                >
                  View details
                </Link>
                {canEdit && (
                  <>
                    <button type="button" className="af-btn af-btn-sm" aria-label={`Edit ${connection.displayName}`} onClick={() => beginEditing(connection)}>
                      <Pencil size={14} /> Edit
                    </button>
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
                  </>
                )}
              </div>
            </div>
            {editingConnection?.id === connection.id && (() => {
              const platform = platforms.data?.find((candidate) => candidate.key === connection.platformKey);
              return (
                <div className="mt-4 flex flex-col gap-4 border-t pt-4" style={{ borderColor: "var(--line)" }}>
                  <label className="flex flex-col gap-1.5 text-sm font-medium">
                    Connection name
                    <input className="af-input" value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} />
                  </label>
                  {platform && (
                    <>
                      <PlatformSetupHint hint={platform.setupHint} manifest={platform.setupManifest} />
                      <div className="grid gap-3 sm:grid-cols-2">
                        {connection.platformKey === "discord" && (
                        <label className="flex flex-col gap-1.5 text-sm font-medium">
                          Browse server
                          <Select value={discordGuildId} onValueChange={setDiscordGuildId}>
                            <SelectTrigger className="w-full"><SelectValue placeholder="Choose a server to browse channels, users, and roles" /></SelectTrigger>
                            <SelectContent><SelectGroup>{(discordGuilds.data ?? []).map((guild) => <SelectItem key={guild.id} value={guild.id}>{guild.label}</SelectItem>)}</SelectGroup></SelectContent>
                          </Select>
                          <span className="text-xs" style={{ color: "var(--ink-4)" }}>Select a server, then choose its channels, users, or roles below. Manual IDs still work.</span>
                        </label>
                      )}
                      <SchemaFields
                        schema={platform.settingsSchema}
                        values={editSettings}
                        onChange={setEditSettings}
                        arraySuggestions={connection.platformKey === "slack"
                          ? { channel_ids: slackChannels.data ?? [], dm_user_ids: slackUsers.data ?? [] }
                          : connection.platformKey === "discord"
                            ? { guild_ids: discordGuilds.data ?? [], allowed_channel_ids: discordChannels.data ?? [], allowed_user_ids: discordUsers.data ?? [], allowed_role_ids: discordRoles.data ?? [] }
                            : {}}
                      />
                      </div>
                      <div className="rounded-lg p-3" style={{ border: "1px solid var(--line)" }}>
                        <div className="mb-1 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>Replace credentials</div>
                        <p className="mb-3 mt-0 text-xs" style={{ color: "var(--ink-3)" }}>Leave every credential blank to keep the encrypted credentials already stored.</p>
                        <div className="flex w-full flex-col gap-3">
                          <SchemaFields schema={platform.credentialsSchema} values={editCredentials} onChange={setEditCredentials} secret />
                        </div>
                      </div>
                    </>
                  )}
                  {formError && <p className="m-0 text-xs" style={{ color: "var(--err)" }}>{formError}</p>}
                  <div className="flex justify-end gap-2">
                    <button type="button" className="af-btn" onClick={() => { setEditingConnection(null); setFormError(null); }}>Cancel</button>
                    <button type="button" className="af-btn af-btn-primary" disabled={!editDisplayName.trim() || updateConnection.isPending} onClick={() => void saveConnection()}>
                      {updateConnection.isPending ? "Saving…" : "Save changes"}
                    </button>
                  </div>
                </div>
              );
            })()}
          </div>
        ))}
        {!connections.isPending && connections.data?.length === 0 && !adding && (
          <div
            className="flex flex-col items-center gap-2 rounded-xl p-6 text-center"
            style={{ border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)", background: "var(--warn-soft)" }}
          >
            <MessageCircleWarning size={20} style={{ color: "var(--warn)" }} />
            <p className="m-0 text-sm font-medium" style={{ color: "var(--ink)" }}>Nobody can message this Agent yet</p>
            <p className="m-0 text-sm" style={{ color: "var(--ink-3)" }}>Connect a messaging platform below to make it reachable.</p>
          </div>
        )}

        {adding && (
          <div className="overflow-hidden rounded-2xl" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="flex flex-col gap-5 p-4 sm:p-5">
              <div>
                <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Choose a platform</div>
                <p className="mb-0 mt-1 text-xs" style={{ color: "var(--ink-3)" }}>
                  You can add more channels later. Each connection has its own credentials and status.
                </p>
                {platforms.isPending && <p className="mb-0 mt-3 text-xs" style={{ color: "var(--ink-3)" }}>Loading platforms…</p>}
                {platforms.error && (
                  <div className="mt-3 flex items-center gap-2 text-xs" style={{ color: "var(--err)" }}>
                    <CircleAlert size={14} /> Could not load available platforms.
                  </div>
                )}
                {platforms.data && platforms.data.length > 0 && (
                  <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                    {platforms.data.map((platform) => (
                      <PlatformOption
                        key={platform.key}
                        platform={platform}
                        selected={platformKey === platform.key}
                        onSelect={() => choosePlatform(platform.key)}
                      />
                    ))}
                  </div>
                )}
              </div>

              {!selectedPlatform ? (
                <div
                  className="flex items-start gap-3 rounded-xl p-3.5"
                  style={{ border: "1px dashed var(--line-strong)", background: "var(--bg-elev)" }}
                >
                  <LockKeyhole size={17} className="mt-0.5 flex-shrink-0" style={{ color: "var(--ink-4)" }} />
                  <div>
                    <div className="text-sm font-medium" style={{ color: "var(--ink)" }}>Your credentials stay private</div>
                    <p className="mb-0 mt-1 text-xs leading-relaxed" style={{ color: "var(--ink-3)" }}>
                      Select a platform to see the small set of details needed to connect it securely.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl p-4 sm:p-5" style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}>
                  <div className="flex items-center gap-3">
                    <span className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-lg" style={{ background: "var(--bg-soft)" }}>
                      <ConnectionIcon platformKey={selectedPlatform.key} size={19} />
                    </span>
                    <div>
                      <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Configure {selectedPlatform.displayName}</div>
                      <p className="mb-0 mt-0.5 text-xs" style={{ color: "var(--ink-3)" }}>Give this connection a recognizable name, then add its credentials.</p>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-col gap-4">
                    <PlatformSetupHint hint={selectedPlatform.setupHint} manifest={selectedPlatform.setupManifest} />
                    <label className="flex flex-col gap-1.5 text-sm font-medium">
                      Connection name
                      <input
                        className="af-input"
                        value={displayName}
                        onChange={(event) => setDisplayName(event.target.value)}
                        placeholder={`${selectedPlatform.displayName} connection`}
                      />
                      <span className="text-xs font-normal" style={{ color: "var(--ink-4)" }}>Only you will see this label in the Agent settings.</span>
                    </label>
                    {schemaProperties(selectedPlatform.settingsSchema).length > 0 && (
                      <div className="flex flex-col gap-2">
                        <div className="text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--ink-4)" }}>Connection settings</div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <SchemaFields schema={selectedPlatform.settingsSchema} values={settings} onChange={setSettings} />
                        </div>
                      </div>
                    )}
                    <div className="rounded-xl p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
                      <div className="flex items-start gap-2.5">
                        <LockKeyhole size={16} className="mt-0.5 flex-shrink-0" style={{ color: "var(--accent-ink)" }} />
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--ink-2)" }}>Credentials</div>
                          <p className="mb-0 mt-1 text-xs leading-relaxed" style={{ color: "var(--ink-3)" }}>
                            Encrypted at rest and never shown again after you save this connection.
                          </p>
                        </div>
                      </div>
                      <div className="mt-4 flex w-full flex-col gap-3">
                        <SchemaFields schema={selectedPlatform.credentialsSchema} values={credentials} onChange={setCredentials} secret />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {(formError || createConnection.error) && (
                <div className="flex items-center gap-2 text-xs" style={{ color: "var(--err)" }} role="alert">
                  <CircleAlert size={14} /> {formError ?? "Could not create the connection."}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 sm:px-5" style={{ borderColor: "var(--line)" }}>
              <div className="inline-flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-4)" }}>
                <LockKeyhole size={13} /> Credentials are encrypted.
              </div>
              <div className="flex gap-2">
                <button type="button" className="af-btn af-btn-ghost" onClick={() => { setAdding(false); setFormError(null); }}>Cancel</button>
                <button
                  type="button"
                  className="af-btn af-btn-primary"
                  disabled={!platformKey || !displayName.trim() || createConnection.isPending}
                  onClick={() => void addConnection()}
                >
                  {createConnection.isPending ? "Connecting…" : selectedPlatform ? `Connect ${selectedPlatform.displayName}` : "Choose a platform"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <ConfirmationDialog
        open={Boolean(retiring)}
        onOpenChange={(open) => { if (!open) setRetiring(null); }}
        title="Remove this connection?"
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
