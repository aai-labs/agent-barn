"use client";

import { useEffect, useRef, useState } from "react";
import JSZip from "jszip";
import { ChevronDownIcon } from "lucide-react";
import { PlusIcon, SearchIcon, XIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  INTEGRATION_PROVIDERS,
  getIntegrationProvider,
  parseGithubRepoUrl,
  type IntegrationDraft,
} from "../integrations";
import type { AgentTemplateRead } from "../schemas";
import { useTemplates } from "../hooks/use-templates";
import { ChoiceCard, FormField, NextStep, TokenInput } from "./hire-dialog-primitives";
import { ModelSelect } from "./model-select";
import { Pagination } from "./pagination";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const HIRE_DIALOG_PAGE_SIZE = 6;

export type WizardStep =
  | "template"
  | "agent-type"
  | "platform-choice"
  | "slack-choice"
  | "config-token"
  | "bot-builder"
  | "slack-tokens"
  | "teams-bot-builder"
  | "teams-credentials"
  | "details"
  | "integrations";

export const TEMPLATE_FILE_KEYS = [
  "soulMd",
  "identityMd",
  "userMd",
  "toolsMd",
  "agentsMd",
  "bootMd",
  "bootstrapMd",
  "heartbeatMd",
] as const;

export type TemplateFileKey = (typeof TEMPLATE_FILE_KEYS)[number];

export function templateFileLabel(key: TemplateFileKey): string {
  return key.replace("Md", "").toUpperCase() + ".md";
}

export const BOT_COLOR_PRESETS = ["#4A154B", "#1264A3", "#2BAC76", "#E8912D", "#CC4400"];

async function fetchAsset(path: string): Promise<Blob> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Unable to load ${path}`);
  return response.blob();
}

function safeFilePrefix(name: string): string {
  const normalized = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return normalized.replace(/^-+|-+$/g, "") || "teams-app";
}

export async function downloadTeamsAppPackage(manifest: string, botName: string): Promise<void> {
  const zip = new JSZip();
  const [colorIcon, outlineIcon] = await Promise.all([
    fetchAsset("/teams-icon-color.png"),
    fetchAsset("/teams-icon-outline.png"),
  ]);

  zip.file("manifest.json", manifest);
  zip.file("color.png", colorIcon);
  zip.file("outline.png", outlineIcon);

  const blob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safeFilePrefix(botName)}-teams-app.zip`;
  a.click();
  URL.revokeObjectURL(url);
}

export function TemplateSourceBadge({ source }: { source: AgentTemplateRead["templateSource"] }) {
  if (source !== "pre-defined") return null;
  return (
    <span
      className="text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
      style={{ color: "var(--ink-3)", background: "var(--line)" }}
    >
      Pre-defined
    </span>
  );
}

// Shared lineage version picker — used at hire time, in the template drawer,
// and in the agent re-pin panel. Marks the highest version as "latest".
export function VersionSelect({
  versions,
  selectedVersion,
  onChange,
  disabled,
  ariaLabel = "Version",
}: {
  versions: AgentTemplateRead[];
  selectedVersion: number | null;
  onChange: (version: number) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const latest = versions[0]?.version;
  const resolved = selectedVersion ?? latest ?? null;
  const displayLabel =
    resolved != null
      ? `v${resolved}${resolved === latest ? " (latest)" : ""}`
      : "Select…";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="af-btn af-btn-sm flex items-center gap-1.5"
          aria-label={ariaLabel}
          disabled={disabled || versions.length === 0}
        >
          <span>{displayLabel}</span>
          <ChevronDownIcon size={12} className="opacity-50 flex-shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuRadioGroup
          value={resolved != null ? String(resolved) : ""}
          onValueChange={(v) => onChange(Number(v))}
        >
          {versions.map((v) => (
            <DropdownMenuRadioItem key={v.version} value={String(v.version)}>
              v{v.version}
              {v.version === latest ? " (latest)" : ""}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ClampedDescription({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [clamped, setClamped] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (el) setClamped(el.scrollHeight > el.clientHeight);
  }, [text]);

  const inner = (
    <div
      ref={ref}
      className="text-[0.75rem] leading-[1.4] overflow-hidden cursor-default"
      style={{
        color: "var(--ink-3)",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
      }}
    >
      {text}
    </div>
  );

  if (!clamped) return inner;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{inner}</TooltipTrigger>
        <TooltipContent side="top">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function TemplateStep({
  selectedSlug,
  onPick,
  versions,
  versionsLoading,
  selectedVersion,
  onVersionChange,
}: {
  selectedSlug: string | null;
  onPick: (template: AgentTemplateRead) => void;
  versions: AgentTemplateRead[];
  versionsLoading: boolean;
  selectedVersion: number | null;
  onVersionChange: (version: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { templates, total, isLoading, error } = useTemplates({
    search: search || undefined,
    page,
    pageSize: HIRE_DIALOG_PAGE_SIZE,
  });

  const totalPages = Math.max(1, Math.ceil(total / HIRE_DIALOG_PAGE_SIZE));


  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
      >
        <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <input
          className="flex-1 text-[0.8125rem] outline-none bg-transparent"
          style={{ color: "var(--ink)" }}
          placeholder="Search templates…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      <div style={{ minHeight: "22rem" }}>
      {isLoading && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
          Loading templates…
        </div>
      )}
      {!isLoading && error && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--err)" }}>
          Could not load templates. Please try again.
        </div>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
          {search ? "No templates match." : "No templates yet. Create one in Settings → Templates first."}
        </div>
      )}

      {!isLoading && !error && templates.length > 0 && (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {templates.map((t) => (
            <div
              key={t.templateSlug}
              className="flex flex-col gap-1.5 p-4 rounded-2xl cursor-default transition-colors min-h-[4.5rem]"
              style={{
                border: selectedSlug === t.templateSlug ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                background: selectedSlug === t.templateSlug ? "var(--bg-soft)" : "var(--bg-elev)",
              }}
              onClick={() => onPick(t)}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>{t.templateName}</div>
                <TemplateSourceBadge source={t.templateSource} />
              </div>
              {t.description && <ClampedDescription text={t.description} />}
              <div className="mt-1">
                {selectedSlug === t.templateSlug ? (
                  <div onClick={(e) => e.stopPropagation()}>
                    {versionsLoading ? (
                      <span className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>Loading…</span>
                    ) : (
                      <VersionSelect
                        versions={versions}
                        selectedVersion={selectedVersion}
                        onChange={onVersionChange}
                      />
                    )}
                  </div>
                ) : (
                  <div className="h-8" />
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      </div>

      <div style={{ minHeight: "1.875rem" }}>
        <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </div>
  );
}

export function ConfigTokenStep({
  tokenInput,
  onTokenInputChange,
  showToken,
  onToggleToken,
  refreshInput,
  onRefreshInputChange,
  showRefresh,
  onToggleRefresh,
  isSaving,
  error,
}: {
  tokenInput: string;
  onTokenInputChange: (v: string) => void;
  showToken: boolean;
  onToggleToken: () => void;
  refreshInput: string;
  onRefreshInputChange: (v: string) => void;
  showRefresh: boolean;
  onToggleRefresh: () => void;
  isSaving: boolean;
  error: string | null;
}) {
  return (
    <div className="flex flex-col gap-5">
      <p className="text-[0.8125rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        To create the Slack app automatically, you need configuration tokens.
      </p>

      <FormField label="Access token" hint="Configuration access token from Slack">
        <TokenInput
          value={tokenInput}
          onChange={onTokenInputChange}
          visible={showToken}
          onToggle={onToggleToken}
          placeholder="Configuration access token..."
          disabled={isSaving}
        />
      </FormField>

      <FormField label="Refresh token" hint="Starts with xoxe- · enables automatic renewal">
        <TokenInput
          value={refreshInput}
          onChange={onRefreshInputChange}
          visible={showRefresh}
          onToggle={onToggleRefresh}
          placeholder="xoxe-…"
          disabled={isSaving}
        />
      </FormField>

      {error && (
        <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
          {error}
        </div>
      )}

      <div
        className="flex flex-col gap-3 rounded-2xl p-4"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <NextStep n={1} label="Go to your Slack apps">
          Open{" "}
          <a
            href="https://api.slack.com/apps"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            api.slack.com/apps ↗
          </a>
        </NextStep>
        <NextStep n={2} label="Open any app's Basic Information page">
          Scroll to <b>App Configuration Tokens</b> and click <b>Generate Token</b>. You will get both an access token and a refresh token.
        </NextStep>
        <NextStep n={3} label="Paste both tokens above">
          They will be saved to your account and reused for future bot creation.
        </NextStep>
      </div>

      <p className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
        You can update these tokens later in{" "}
        <a href="/dashboard/account" className="underline" style={{ color: "var(--ink-3)" }}>
          Account settings
        </a>.
      </p>
    </div>
  );
}

export function SlackChoiceStep({
  setupNewBot,
  onChange,
}: {
  setupNewBot: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <ChoiceCard
        selected={setupNewBot}
        onClick={() => onChange(true)}
        title="Set up a new Slack bot"
        description="We'll generate a manifest so you can create one in seconds."
      />
      <ChoiceCard
        selected={!setupNewBot}
        onClick={() => onChange(false)}
        title="I already have a Slack app"
        description="Skip straight to entering your app and bot tokens."
      />
    </div>
  );
}

export function BotBuilderStep({
  botName,
  onBotNameChange,
  botDescription,
  onBotDescriptionChange,
  botColor,
  onBotColorChange,
}: {
  botName: string;
  onBotNameChange: (v: string) => void;
  botDescription: string;
  onBotDescriptionChange: (v: string) => void;
  botColor: string;
  onBotColorChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <FormField label="Bot display name" hint="Shown in Slack — can be changed later">
        <input
          className="af-input"
          value={botName}
          onChange={(e) => onBotNameChange(e.target.value)}
          placeholder="Aria"
        />
      </FormField>

      <FormField label="Description" hint="Short summary shown in the Slack app directory">
        <input
          className="af-input"
          value={botDescription}
          onChange={(e) => onBotDescriptionChange(e.target.value)}
          placeholder="Handles tasks and reduces day-to-day friction."
        />
      </FormField>

      <FormField label="Background color" hint="Used in Slack's bot icon background">
        <div className="flex items-center gap-2.5 flex-wrap">
          {BOT_COLOR_PRESETS.map((c) => (
            <button
              key={c}
              className="w-7 h-7 rounded-full border-2 transition-all"
              style={{
                background: c,
                borderColor: botColor === c ? "var(--ink)" : "transparent",
                outline: botColor === c ? "2px solid var(--bg-elev)" : "none",
                outlineOffset: "-3px",
              }}
              onClick={() => onBotColorChange(c)}
              aria-label={c}
            />
          ))}
          <input
            className="af-input font-mono w-28"
            value={botColor}
            onChange={(e) => onBotColorChange(e.target.value)}
            placeholder="#4A154B"
            maxLength={7}
          />
        </div>
      </FormField>
    </div>
  );
}

export function SlackTokensStep({
  slackAppToken,
  onAppTokenChange,
  slackBotToken,
  onBotTokenChange,
  showAppToken,
  onToggleAppToken,
  showBotToken,
  onToggleBotToken,
  error,
  appId,
  botTokenUrl,
  appTokenUrl,
}: {
  slackAppToken: string;
  onAppTokenChange: (v: string) => void;
  slackBotToken: string;
  onBotTokenChange: (v: string) => void;
  showAppToken: boolean;
  onToggleAppToken: () => void;
  showBotToken: boolean;
  onToggleBotToken: () => void;
  error: string | null;
  appId?: string | null;
  botTokenUrl?: string | null;
  appTokenUrl?: string | null;
}) {
  return (
    <form autoComplete="off" className="flex flex-col gap-5" onSubmit={(e) => e.preventDefault()}>
      <div
        className="flex flex-col gap-3.5 p-4 rounded-2xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div>
          <div className="font-semibold text-[0.844rem] mb-0.5" style={{ color: "var(--ink)" }}>
            Slack credentials
          </div>
          <div className="text-[0.781rem]" style={{ color: "var(--ink-3)" }}>
            These stay encrypted in the key vault. The agent only sees fake placeholders.
          </div>
        </div>

        <FormField label="App-level token" hint="Starts with xapp- · required for Socket Mode">
          <TokenInput
            value={slackAppToken}
            onChange={onAppTokenChange}
            visible={showAppToken}
            onToggle={onToggleAppToken}
            placeholder="xapp-1-…"
          />
        </FormField>

        <FormField label="Bot token" hint="Starts with xoxb- · required for API calls">
          <TokenInput
            value={slackBotToken}
            onChange={onBotTokenChange}
            visible={showBotToken}
            onToggle={onToggleBotToken}
            placeholder="xoxb-…"
          />
        </FormField>

        {error && (
          <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
            {error}
          </div>
        )}
      </div>

      {appId && (
        <div
          className="flex flex-col gap-3 rounded-2xl p-4"
          style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
        >
          <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Your Slack app is created!
          </div>
          <NextStep n={1} label="Install the app to your workspace">
            Go to{" "}
            <a
              href={botTokenUrl ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
              style={{ color: "var(--ink-2)" }}
            >
              OAuth &amp; Permissions ↗
            </a>
            {" "}and click <b>Install to Workspace</b>. After installing, the page will show a <b>Bot User OAuth Token</b> (<span className="font-mono text-xs">xoxb-…</span>) — copy it.
          </NextStep>
          <NextStep n={2} label="Generate an App-Level Token">
            Go to{" "}
            <a
              href={appTokenUrl ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
              style={{ color: "var(--ink-2)" }}
            >
              Basic Information ↗
            </a>
            {" "}→ scroll to <b>App-Level Tokens</b> → click <b>Generate Token and Scopes</b>. Name it anything, add the <span className="font-mono text-xs">connections:write</span> scope, and copy the generated <span className="font-mono text-xs">xapp-…</span> token.
          </NextStep>
          <NextStep n={3} label="Paste both tokens above" />
        </div>
      )}
    </form>
  );
}

export function PlatformChoiceStep({
  platform,
  onChange,
}: {
  platform: "slack" | "teams";
  onChange: (v: "slack" | "teams") => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <ChoiceCard
        selected={platform === "slack"}
        onClick={() => onChange("slack")}
        title="Slack"
        description="Connect via Socket Mode with a bot and app-level token. Recommended."
      />
      <ChoiceCard
        selected={platform === "teams"}
        onClick={() => onChange("teams")}
        title="Microsoft Teams"
        description="Connect via Azure Bot Framework with a webhook endpoint."
      />
    </div>
  );
}

export function AgentTypeStep({
  agentType,
  onChange,
}: {
  agentType: "openclaw" | "hermes";
  onChange: (v: "openclaw" | "hermes") => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <ChoiceCard
        selected={agentType === "hermes"}
        onClick={() => onChange("hermes")}
        title="Hermes"
        description="Slack-only. Fast, lightweight, plugin-based. Recommended."
      />
      <ChoiceCard
        selected={agentType === "openclaw"}
        onClick={() => onChange("openclaw")}
        title="OpenClaw"
        description="Slack and Microsoft Teams. Full platform support."
      />
    </div>
  );
}

export function generateTeamsManifest(
  appId: string,
  botName: string,
  botDescription: string,
  accentColor: string,
): string {
  return JSON.stringify(
    {
      $schema:
        "https://developer.microsoft.com/en-us/json-schemas/teams/v1.13/MicrosoftTeams.schema.json",
      manifestVersion: "1.13",
      version: "1.0.0",
      id: appId || "{{YOUR_APP_ID}}",
      packageName: "com.agentfarm.bot",
      developer: {
        name: "Agent Farm",
        websiteUrl: "https://agent-farm.k8s.aai-labs.com",
        privacyUrl: "https://agent-farm.k8s.aai-labs.com",
        termsOfUseUrl: "https://agent-farm.k8s.aai-labs.com",
      },
      name: { short: botName, full: `${botName} - Agent Farm` },
      description: {
        short: botDescription,
        full: `${botDescription}\n\nPowered by Agent Farm.`,
      },
      icons: { color: "color.png", outline: "outline.png" },
      accentColor,
      bots: [
        {
          botId: appId || "{{YOUR_APP_ID}}",
          scopes: ["personal", "team", "groupchat"],
          supportsFiles: false,
          isNotificationOnly: false,
        },
      ],
      permissions: ["identity", "messageTeamMembers"],
      validDomains: [],
    },
    null,
    2,
  );
}

export function TeamsBotBuilderStep({
  teamsAppId,
  onTeamsAppIdChange,
  botName,
  onBotNameChange,
  botDescription,
  onBotDescriptionChange,
  botColor,
  onBotColorChange,
}: {
  teamsAppId: string;
  onTeamsAppIdChange: (v: string) => void;
  botName: string;
  onBotNameChange: (v: string) => void;
  botDescription: string;
  onBotDescriptionChange: (v: string) => void;
  botColor: string;
  onBotColorChange: (v: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const manifest = generateTeamsManifest(teamsAppId, botName, botDescription, botColor);

  function copyManifest() {
    void navigator.clipboard.writeText(manifest).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function downloadPackage() {
    void downloadTeamsAppPackage(manifest, botName);
  }

  return (
    <div className="flex flex-col gap-5">
      <FormField label="App (client) ID" hint="From your Azure Bot registration — found under Configuration">
        <input
          className="af-input font-mono text-[0.8125rem]"
          value={teamsAppId}
          onChange={(e) => onTeamsAppIdChange(e.target.value)}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </FormField>

      <FormField label="Bot display name" hint="Shown in Teams — can be changed later">
        <input
          className="af-input"
          value={botName}
          onChange={(e) => onBotNameChange(e.target.value)}
          placeholder="Aria"
        />
      </FormField>

      <FormField label="Description" hint="Short summary shown in the Teams app directory">
        <input
          className="af-input"
          value={botDescription}
          onChange={(e) => onBotDescriptionChange(e.target.value)}
          placeholder="Handles tasks and reduces day-to-day friction."
        />
      </FormField>

      <FormField label="Accent color" hint="Used in the Teams app icon background">
        <div className="flex items-center gap-2.5 flex-wrap">
          {BOT_COLOR_PRESETS.map((c) => (
            <button
              key={c}
              className="w-7 h-7 rounded-full border-2 transition-all"
              style={{
                background: c,
                borderColor: botColor === c ? "var(--ink)" : "transparent",
                outline: botColor === c ? "2px solid var(--bg-elev)" : "none",
                outlineOffset: "-3px",
              }}
              onClick={() => onBotColorChange(c)}
              aria-label={c}
            />
          ))}
          <input
            className="af-input font-mono w-28"
            value={botColor}
            onChange={(e) => onBotColorChange(e.target.value)}
            placeholder="#4A154B"
            maxLength={7}
          />
        </div>
      </FormField>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Teams app package
          </span>
          <div className="flex gap-1.5">
            <button className="af-btn af-btn-sm" onClick={copyManifest}>
              {copied ? "Copied!" : "Copy"}
            </button>
            <button className="af-btn af-btn-sm" onClick={downloadPackage}>
              Download Teams app package
            </button>
          </div>
        </div>
        <pre
          className="rounded-xl font-mono text-[0.719rem] leading-[1.6] p-4 overflow-x-auto"
          style={{
            background: "var(--bg-elev)",
            border: "1px solid var(--line)",
            color: "var(--ink-2)",
            maxHeight: "14rem",
          }}
        >
          {manifest}
        </pre>
      </div>

      <div
        className="flex flex-col gap-3 rounded-2xl p-4"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
          What to do next
        </div>
        <NextStep n={1} label="Download the Teams app package">
          Use the download above after you review the manifest details. The zip is ready to upload.
        </NextStep>
        <NextStep n={2} label="Upload to Teams">
          In Teams, go to <b>Apps</b>, open <b>Manage your apps</b>, choose <b>Upload a custom app</b>, and upload the zip.
        </NextStep>
        <NextStep n={3} label="Publish or approve if prompted">
          If your tenant requires admin review, publish or approve the submitted app in Teams admin center.
        </NextStep>
        <NextStep n={4} label="Install and test">
          Open the app in Teams and send a message after the agent is hired and the messaging endpoint is configured.
        </NextStep>
      </div>
    </div>
  );
}

export function TeamsCredentialsStep({
  teamsAppId,
  onAppIdChange,
  teamsAppPassword,
  onAppPasswordChange,
  showAppPassword,
  onToggleAppPassword,
  teamsTenantId,
  onTenantIdChange,
  error,
}: {
  teamsAppId: string;
  onAppIdChange: (v: string) => void;
  teamsAppPassword: string;
  onAppPasswordChange: (v: string) => void;
  showAppPassword: boolean;
  onToggleAppPassword: () => void;
  teamsTenantId: string;
  onTenantIdChange: (v: string) => void;
  error: string | null;
}) {
  return (
    <form autoComplete="off" className="flex flex-col gap-5" onSubmit={(e) => e.preventDefault()}>
      <div
        className="flex flex-col gap-3.5 p-4 rounded-2xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div>
          <div className="font-semibold text-[0.844rem] mb-0.5" style={{ color: "var(--ink)" }}>
            Azure credentials
          </div>
          <div className="text-[0.781rem]" style={{ color: "var(--ink-3)" }}>
            These stay encrypted in the key vault. The agent only sees fake placeholders.
          </div>
        </div>

        <FormField label="App (client) ID" hint="From your Azure Bot registration — found under Configuration">
          <input
            className="af-input font-mono text-[0.8125rem]"
            value={teamsAppId}
            onChange={(e) => onAppIdChange(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          />
        </FormField>

        <FormField label="App password (client secret)" hint="Created in Azure App Registration → Certificates & secrets">
          <TokenInput
            value={teamsAppPassword}
            onChange={onAppPasswordChange}
            visible={showAppPassword}
            onToggle={onToggleAppPassword}
            placeholder="Client secret value"
          />
        </FormField>

        <FormField label="Tenant ID" hint="Found in Azure Portal → Azure Active Directory → Overview">
          <input
            className="af-input font-mono text-[0.8125rem]"
            value={teamsTenantId}
            onChange={(e) => onTenantIdChange(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          />
        </FormField>

        {error && (
          <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
            {error}
          </div>
        )}
      </div>

      <div
        className="flex flex-col gap-3 rounded-2xl p-4"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
          What to do next
        </div>
        <NextStep n={1} label="Create an Azure Bot resource">
          Go to the{" "}
          <a
            href="https://portal.azure.com/#create/Microsoft.AzureBot"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            Azure Portal →
          </a>
          {" "}and create an Azure Bot resource.
        </NextStep>
        <NextStep n={2} label="Copy the App ID">
          In the Bot resource, open <b>Configuration</b> and copy the Microsoft App ID.
        </NextStep>
        <NextStep n={3} label="Create an app password">
          Open the linked app registration, go to <b>Certificates &amp; secrets</b>, and create a new client secret.
          Copy the secret value before leaving the page.
        </NextStep>
        <NextStep n={4} label="Copy the Tenant ID">
          In Azure, open <b>Microsoft Entra ID</b> → <b>Overview</b> and copy the Tenant ID.
        </NextStep>
        <NextStep n={5} label="Enable the Teams channel">
          In your Bot resource, go to <b>Channels</b> and enable <b>Microsoft Teams</b>.
        </NextStep>
      </div>
    </form>
  );
}

export function DetailsStep({
  template,
  platform,
  name,
  onNameChange,
  model,
  onModelChange,
  slackGroupPolicy,
  onSlackGroupPolicyChange,
  slackDmPolicy,
  onSlackDmPolicyChange,
  onChangeTemplate,
}: {
  template: AgentTemplateRead;
  platform: "slack" | "teams";
  name: string;
  onNameChange: (v: string) => void;
  model: string;
  onModelChange: (v: string) => void;
  slackGroupPolicy: string;
  onSlackGroupPolicyChange: (v: string) => void;
  slackDmPolicy: string;
  onSlackDmPolicyChange: (v: string) => void;
  onChangeTemplate: () => void;
}) {
  const [previewFile, setPreviewFile] = useState<TemplateFileKey>("soulMd");
  return (
    <div className="flex flex-col gap-5">
      <div
        className="flex items-center gap-3 p-4 rounded-2xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="text-2xl">🤖</div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <div className="font-semibold text-sm" style={{ color: "var(--ink)" }}>{template.templateName}</div>
            <TemplateSourceBadge source={template.templateSource} />
          </div>
          <div className="text-[0.8125rem] font-mono" style={{ color: "var(--ink-3)" }}>
            v{template.version}
          </div>
        </div>
        <button className="af-btn af-btn-sm af-btn-ghost" onClick={onChangeTemplate}>Change</button>
      </div>

      <FormField label="Name them" hint="Suggested: Aria">
        <input
          className="af-input af-input-lg"
          aria-label="Name them"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="Aria"
        />
      </FormField>

      <FormField label="Model">
        <ModelSelect value={model} onChange={onModelChange} aria-label="Model" />
      </FormField>

      {platform === "slack" && (
        <>
          <FormField label="Channel access" hint="You can add specific channels after hiring">
            <select
              className="af-input"
              value={slackGroupPolicy}
              onChange={(e) => onSlackGroupPolicyChange(e.target.value)}
            >
              <option value="allowlist">Allowlist — only allowed channels</option>
              <option value="open">Open — respond in any channel</option>
            </select>
          </FormField>

          <FormField label="Direct messages">
            <select
              className="af-input"
              value={slackDmPolicy}
              onChange={(e) => onSlackDmPolicyChange(e.target.value)}
            >
              <option value="off">Off — ignore direct messages</option>
              <option value="allowlist">Allowlist — only allowed users</option>
              <option value="open">Open — anyone can DM</option>
            </select>
          </FormField>
        </>
      )}

      <details className="rounded-2xl overflow-hidden" style={{ border: "1px solid var(--line)" }}>
        <summary
          className="px-4 py-3 text-[0.844rem] font-medium cursor-default"
          style={{ color: "var(--ink-2)", background: "var(--bg-elev)" }}
        >
          Review configuration files
        </summary>
        <div className="p-4 flex flex-col gap-3" style={{ background: "var(--bg-soft)" }}>
          <div className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
            Read-only preview of <span className="font-mono">v{template.version}</span>.
            {" "}<span className="font-mono">{"{{ … }}"}</span> placeholders are filled in when the agent starts.
            To customise, edit the template in Settings → Templates.
          </div>
          <div className="flex flex-wrap gap-1">
            {TEMPLATE_FILE_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                className="af-btn af-btn-sm"
                style={{
                  background: previewFile === key ? "var(--ink)" : undefined,
                  color: previewFile === key ? "var(--bg)" : undefined,
                }}
                onClick={() => setPreviewFile(key)}
              >
                {templateFileLabel(key)}
              </button>
            ))}
          </div>
          <textarea
            className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none"
            rows={10}
            readOnly
            aria-label={`${templateFileLabel(previewFile)} preview`}
            value={template[previewFile]}
          />
        </div>
      </details>
    </div>
  );
}

export function IntegrationsStep({
  integrations,
  onChange,
}: {
  integrations: IntegrationDraft[];
  onChange: (next: IntegrationDraft[]) => void;
}) {
  const [visible, setVisible] = useState<Record<string, boolean>>({});

  const usedProviders = new Set(integrations.map((i) => i.provider));
  const available = INTEGRATION_PROVIDERS.filter((p) => !usedProviders.has(p.id));

  function addProvider(id: string) {
    onChange([...integrations, { provider: id, content: {} }]);
  }
  function removeProvider(id: string) {
    onChange(integrations.filter((i) => i.provider !== id));
  }
  function setField(providerId: string, key: string, value: string) {
    onChange(
      integrations.map((i) =>
        i.provider === providerId
          ? { ...i, content: { ...i.content, [key]: value } }
          : i,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[0.8125rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Connect external tools your agent can use. Credentials are encrypted in the key vault.
        {" This step is optional — you can hire without any."}
      </p>

      {/* Connected integrations. */}
      {integrations.map((draft) => {
        const provider = getIntegrationProvider(draft.provider);
        if (!provider) return null;
        return (
          <div
            key={draft.provider}
            className="flex flex-col gap-3.5 p-4 rounded-2xl"
            style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
          >
            <div className="flex items-center justify-between">
              <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                {provider.label}
              </div>
              <button
                type="button"
                className="af-btn af-btn-ghost af-btn-icon"
                onClick={() => removeProvider(draft.provider)}
                aria-label={`Remove ${provider.label}`}
              >
                <XIcon size={15} />
              </button>
            </div>

            {provider.fields.map((field) => {
              const value = draft.content[field.key] ?? "";
              const label = field.required ? field.label : `${field.label} (optional)`;
              if (field.type === "secret") {
                const vkey = `${draft.provider}:${field.key}`;
                return (
                  <FormField key={field.key} label={label} hint={field.hint}>
                    <TokenInput
                      value={value}
                      onChange={(v) => setField(draft.provider, field.key, v)}
                      visible={!!visible[vkey]}
                      onToggle={() => setVisible((s) => ({ ...s, [vkey]: !s[vkey] }))}
                      placeholder={field.placeholder}
                    />
                  </FormField>
                );
              }
              if (field.type === "repo-url") {
                const parsed = parseGithubRepoUrl(value);
                const invalid = value.length > 0 && !parsed;
                return (
                  <FormField key={field.key} label={label} hint={field.hint}>
                    <input
                      className={`af-input${invalid ? " border-red-400" : ""}`}
                      value={value}
                      onChange={(e) => setField(draft.provider, field.key, e.target.value)}
                      placeholder={field.placeholder}
                      autoComplete="off"
                    />
                    {parsed && (
                      <p className="text-[0.75rem] mt-1" style={{ color: "var(--ink-3)" }}>
                        owner: <strong>{parsed.owner}</strong> · repo: <strong>{parsed.repo}</strong>
                      </p>
                    )}
                    {invalid && (
                      <p className="text-[0.75rem] mt-1 text-red-500">
                        Must be a valid GitHub URL, e.g. https://github.com/owner/repo.git
                      </p>
                    )}
                  </FormField>
                );
              }
              return (
                <FormField key={field.key} label={label} hint={field.hint}>
                  <input
                    className="af-input"
                    value={value}
                    onChange={(e) => setField(draft.provider, field.key, e.target.value)}
                    placeholder={field.placeholder}
                    autoComplete="off"
                  />
                </FormField>
              );
            })}
          </div>
        );
      })}

      {available.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Add an integration
          </div>
          <div className="flex flex-wrap gap-2">
            {available.map((p) => (
              <button
                key={p.id}
                type="button"
                className="af-btn af-btn-sm flex items-center gap-1.5"
                onClick={() => addProvider(p.id)}
              >
                <PlusIcon size={14} /> {p.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
