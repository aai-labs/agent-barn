"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SharedManualToggle } from "@/features/shared-credentials/components/shared-manual-toggle";
import { useSharedManualSwitch } from "@/features/shared-credentials/hooks/use-shared-manual-switch";
import { SHARED_CREDENTIAL_PROVIDER_LABELS } from "@/features/shared-credentials/utils";
import { useSkills } from "@/features/skills/hooks/use-skills";
import { SKILL_PROVIDER_LABELS } from "@/features/skills/utils";
import type { Skill } from "@/features/skills/schemas";
import { SkillSourceBadge } from "@/features/skills/components/skill-source-badge";

import {
  INTEGRATION_PROVIDERS,
  getIntegrationProvider,
  isAutoConfiguredProvider,
  type IntegrationDraft,
} from "../integrations";
import type { AgentAssignedSkill, AgentTemplateRead, TemplateRequiredSkill } from "../schemas";
import { useTemplates } from "../hooks/use-templates";
import type { RequiredSkillGroup } from "../utils";
import { ChoiceCard, FormField, NextStep, TokenInput } from "./hire-dialog-primitives";
import { IntegrationFields } from "./integration-fields";
import { ModelSelect } from "./model-select";
import { Pagination } from "./pagination";

const HIRE_DIALOG_PAGE_SIZE = 6;

export type WizardStep =
  | "template"
  | "agent-type"
  | "platform-choice"
  | "slack-choice"
  | "config-token"
  | "bot-builder"
  | "slack-tokens"
  | "telegram-token"
  | "details"
  | "skills";

export const TEMPLATE_FILE_KEYS = [
  "soulMd",
  "identityMd",
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

export function TemplateSourceBadge({
  source,
  isFork = false,
}: {
  source: AgentTemplateRead["templateSource"];
  isFork?: boolean;
}) {
  if (source !== "pre-defined") return null;
  return (
    <span
      className="text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
      style={
        isFork
          ? { color: "var(--accent-ink)", background: "var(--accent-soft)" }
          : { color: "var(--ink-3)", background: "var(--line)" }
      }
      title={isFork ? "Organization fork of a Platform Template" : "Platform Template"}
    >
      {isFork ? "Org fork" : "Built-in"}
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
  selectedKey,
  onPick,
  versions,
  versionsLoading,
  selectedVersion,
  onVersionChange,
}: {
  selectedKey: string | null;
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
              key={t.templateKey}
              className="flex flex-col gap-1.5 p-4 rounded-2xl cursor-default transition-colors min-h-[4.5rem]"
              style={{
                border: selectedKey === t.templateKey ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                background: selectedKey === t.templateKey ? "var(--bg-soft)" : "var(--bg-elev)",
              }}
              onClick={() => onPick(t)}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>{t.templateName}</div>
                <TemplateSourceBadge
                  source={t.templateSource}
                  isFork={Boolean(t.forkedFromPlatformTemplateId)}
                />
              </div>
              {t.description && <ClampedDescription text={t.description} />}
              <div className="mt-1">
                {selectedKey === t.templateKey ? (
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
        <NextStep n={2} label="Scroll to App Configuration Tokens">
          It&apos;s at the bottom of the page. Click <b>Generate Token</b> — you will get both an access token and a refresh token.
        </NextStep>
        <NextStep n={3} label="Paste both tokens above">
          They will be saved to your account and reused for future bot creation.
        </NextStep>
      </div>

      <p className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
        You can update these tokens later in{" "}
        <Link href="/dashboard/account" className="underline" style={{ color: "var(--ink-3)" }}>
          Account settings
        </Link>.
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
        description="We'll automatically create your Slack app in seconds."
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

const SLACK_EXAMPLE_MANIFEST = JSON.stringify(
  {
    display_information: {
      name: "Your Bot Name",
      description: "Your bot description.",
      background_color: "#4A154B",
    },
    features: {
      app_home: {
        home_tab_enabled: false,
        messages_tab_enabled: true,
        messages_tab_read_only_enabled: false,
      },
      bot_user: {
        display_name: "Your Bot Name",
        always_online: true,
      },
    },
    oauth_config: {
      scopes: {
        bot: [
          "app_mentions:read", "canvases:read", "canvases:write",
          "channels:history", "channels:join", "channels:read",
          "chat:write", "chat:write.customize", "chat:write.public",
          "emoji:read", "files:read", "files:write",
          "groups:history", "groups:read",
          "im:history", "im:read", "im:write",
          "mpim:history", "mpim:read", "mpim:write",
          "pins:read", "pins:write",
          "reactions:read", "reactions:write",
          "search:read.users", "users:read", "users:read.email",
        ],
      },
      pkce_enabled: false,
    },
    settings: {
      event_subscriptions: {
        bot_events: [
          "app_mention", "channel_rename",
          "member_joined_channel", "member_left_channel",
          "message.channels", "message.groups", "message.im", "message.mpim",
          "pin_added", "pin_removed",
          "reaction_added", "reaction_removed",
        ],
      },
      interactivity: { is_enabled: true },
      org_deploy_enabled: false,
      socket_mode_enabled: true,
      token_rotation_enabled: false,
      is_mcp_enabled: false,
    },
  },
  null,
  2,
);

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
  const [manifestCopied, setManifestCopied] = useState(false);

  function copyManifest() {
    void navigator.clipboard.writeText(SLACK_EXAMPLE_MANIFEST).then(() => {
      setManifestCopied(true);
      setTimeout(() => setManifestCopied(false), 2000);
    });
  }

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
          {slackAppToken && !slackAppToken.startsWith("xapp-") && (
            <div className="text-[0.75rem] mt-1" style={{ color: "var(--err)" }}>
              App-level tokens start with xapp-
            </div>
          )}
        </FormField>

        <FormField label="Bot token" hint="Starts with xoxb- · required for API calls">
          <TokenInput
            value={slackBotToken}
            onChange={onBotTokenChange}
            visible={showBotToken}
            onToggle={onToggleBotToken}
            placeholder="xoxb-…"
          />
          {slackBotToken && !slackBotToken.startsWith("xoxb-") && (
            <div className="text-[0.75rem] mt-1" style={{ color: "var(--err)" }}>
              Bot tokens start with xoxb-
            </div>
          )}
        </FormField>

        {error && (
          <div className="text-[0.8125rem]" style={{ color: "var(--err)" }}>
            {error}
          </div>
        )}
      </div>

      {!appId && (
        <div
          className="flex flex-col gap-3 rounded-2xl p-4"
          style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
        >
          <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Configure your existing Slack app
          </div>
          <NextStep n={1} label="Apply the manifest">
            Go to{" "}
            <a
              href="https://api.slack.com/apps"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
              style={{ color: "var(--ink-2)" }}
            >
              api.slack.com/apps ↗
            </a>
            {" "}→ open your app → <b>Features → App Manifest</b>. Paste the manifest below (or merge the scopes and settings into your existing one) and click <b>Save Changes</b>. Update the <span className="font-mono text-xs">name</span> and <span className="font-mono text-xs">description</span> fields to match your bot.
          </NextStep>
          <NextStep n={2} label="Generate an App-Level Token">
            Go to <b>Basic Information</b> → scroll to <b>App-Level Tokens</b> → click <b>Generate Token and Scopes</b>. Name it anything, add the <span className="font-mono text-xs">connections:write</span> scope, and copy the generated <span className="font-mono text-xs">xapp-…</span> token.
          </NextStep>
          <NextStep n={3} label="Install the app to your workspace">
            Go to <b>Install App</b> and click <b>Install to Workspace</b>. After installing, copy the <b>Bot User OAuth Token</b> (<span className="font-mono text-xs">xoxb-…</span>).
          </NextStep>
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
                Manifest
              </span>
              <button type="button" className="af-btn af-btn-sm" onClick={copyManifest}>
                {manifestCopied ? "Copied!" : "Copy"}
              </button>
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
              {SLACK_EXAMPLE_MANIFEST}
            </pre>
          </div>
        </div>
      )}

      {appId && (
        <div
          className="flex flex-col gap-3 rounded-2xl p-4"
          style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
        >
          <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Your Slack app is created!
          </div>
          <NextStep n={1} label="Generate an App-Level Token">
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
          <NextStep n={2} label="Install the app to your workspace">
            Go to{" "}
            <a
              href={botTokenUrl ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
              style={{ color: "var(--ink-2)" }}
            >
              Install App ↗
            </a>
            {" "}and click <b>Install to Workspace</b>. After installing, the page will show a <b>Bot User OAuth Token</b> (<span className="font-mono text-xs">xoxb-…</span>) — copy it.
          </NextStep>
          <NextStep n={3} label="Paste both tokens above" />
        </div>
      )}
    </form>
  );
}

export function TelegramTokenStep({
  token,
  onTokenChange,
  showToken,
  onToggleToken,
  error,
}: {
  token: string;
  onTokenChange: (v: string) => void;
  showToken: boolean;
  onToggleToken: () => void;
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
            Telegram bot token
          </div>
          <div className="text-[0.781rem]" style={{ color: "var(--ink-3)" }}>
            The token stays encrypted in the key vault. The agent only sees fake placeholders.
          </div>
        </div>

        <FormField label="Bot token" hint="From @BotFather — looks like 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11">
          <TokenInput
            value={token}
            onChange={onTokenChange}
            visible={showToken}
            onToggle={onToggleToken}
            placeholder="123456:ABC-DEF…"
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
          How to get a bot token
        </div>
        <NextStep n={1} label="Open @BotFather in Telegram">
          Search for <b>@BotFather</b> in Telegram, or open{" "}
          <a
            href="https://t.me/botfather"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            t.me/botfather ↗
          </a>
        </NextStep>
        <NextStep n={2} label="Create a new bot">
          Send <b>/newbot</b>, choose a display name and a username (must end in &quot;bot&quot;).
        </NextStep>
        <NextStep n={3} label="Copy the token">
          BotFather will send a message containing your bot token. Paste it above.
        </NextStep>
        <NextStep n={4} label="Enable group messaging (optional)">
          To receive all messages in groups (not just @mentions), disable Group Privacy:
          open <b>@BotFather</b> → <b>/mybots</b> → select your bot → <b>Bot Settings</b> → <b>Group Privacy</b> → <b>Turn off</b>.
        </NextStep>
      </div>
    </form>
  );
}

export function PlatformChoiceStep({
  platform,
  onChange,
}: {
  platform: "slack" | "telegram";
  onChange: (v: "slack" | "telegram") => void;
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
        selected={platform === "telegram"}
        onClick={() => onChange("telegram")}
        title="Telegram"
        description="Connect with a bot token from @BotFather. One token, one step."
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
        description="Slack and Telegram. Fast, lightweight, plugin-based. Recommended."
      />
      <ChoiceCard
        selected={agentType === "openclaw"}
        onClick={() => onChange("openclaw")}
        title="OpenClaw"
        description="Slack and Telegram. Full platform support with multi-channel routing."
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
        name: "Agent Barn",
        websiteUrl: "https://agent-farm.k8s.aai-labs.com",
        privacyUrl: "https://agent-farm.k8s.aai-labs.com",
        termsOfUseUrl: "https://agent-farm.k8s.aai-labs.com",
      },
      name: { short: botName, full: `${botName} - Agent Barn` },
      description: {
        short: botDescription,
        full: `${botDescription}\n\nPowered by Agent Barn.`,
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
  agentType,
  name,
  onNameChange,
  model,
  onModelChange,
  slackGroupPolicy,
  onSlackGroupPolicyChange,
  slackDmPolicy,
  onSlackDmPolicyChange,
  slackVerboseMode,
  onSlackVerboseModeChange,
  telegramGroupPolicy,
  onTelegramGroupPolicyChange,
  telegramDmPolicy,
  onTelegramDmPolicyChange,
  approvalMode,
  onApprovalModeChange,
  onChangeTemplate,
}: {
  template: AgentTemplateRead;
  platform: "slack" | "telegram";
  agentType: "openclaw" | "hermes";
  name: string;
  onNameChange: (v: string) => void;
  model: string;
  onModelChange: (v: string) => void;
  slackGroupPolicy: string;
  onSlackGroupPolicyChange: (v: string) => void;
  slackDmPolicy: string;
  onSlackDmPolicyChange: (v: string) => void;
  slackVerboseMode: boolean;
  onSlackVerboseModeChange: (v: boolean) => void;
  telegramGroupPolicy: string;
  onTelegramGroupPolicyChange: (v: string) => void;
  telegramDmPolicy: string;
  onTelegramDmPolicyChange: (v: string) => void;
  approvalMode: string;
  onApprovalModeChange: (v: string) => void;
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
            <TemplateSourceBadge
              source={template.templateSource}
              isFork={Boolean(template.forkedFromPlatformTemplateId)}
            />
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

      {agentType === "hermes" && (
        <FormField label="Command approval">
          <select
            className="af-input"
            value={approvalMode}
            onChange={(e) => onApprovalModeChange(e.target.value)}
          >
            <option value="auto">Auto — approve low-risk commands automatically</option>
            <option value="manual">Manual — always ask before running commands</option>
            <option value="off">Off — skip all approval prompts</option>
          </select>
        </FormField>
      )}

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

          {agentType === "hermes" && (
            <FormField
              label="Verbosity"
              hint="When verbose, the agent announces what it's about to do at each step."
            >
              <select
                className="af-input"
                value={slackVerboseMode ? "verbose" : "concise"}
                onChange={(e) => onSlackVerboseModeChange(e.target.value === "verbose")}
              >
                <option value="verbose">Verbose — announces each step</option>
                <option value="concise">Concise — final answers only</option>
              </select>
            </FormField>
          )}
        </>
      )}

      {platform === "telegram" && (
        <>
          <FormField label="Group access" hint="You can add specific groups after hiring">
            <select
              className="af-input"
              value={telegramGroupPolicy}
              onChange={(e) => onTelegramGroupPolicyChange(e.target.value)}
            >
              <option value="open">Open — respond in any group</option>
              <option value="allowlist">Allowlist — only allowed groups</option>
            </select>
          </FormField>

          <FormField label="Direct messages">
            <select
              className="af-input"
              value={telegramDmPolicy}
              onChange={(e) => onTelegramDmPolicyChange(e.target.value)}
            >
              <option value="open">Open — anyone can DM</option>
              <option value="allowlist">Allowlist — only allowed users</option>
              <option value="off">Off — ignore direct messages</option>
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

// Free-text repeatable list of repo names — Enter/Add appends a chip, X removes one.
export function SkillsStep({
  selectedSkillIds,
  skillCredentials,
  onSkillIdsChange,
  onSkillCredentialsChange,
  templateRequiredSkills = [],
  requiredGroups = [],
  groupChoices = {},
  onGroupChoiceChange,
  platform,
}: {
  selectedSkillIds: string[];
  skillCredentials: IntegrationDraft[];
  onSkillIdsChange: (ids: string[]) => void;
  onSkillCredentialsChange: (drafts: IntegrationDraft[]) => void;
  templateRequiredSkills?: AgentAssignedSkill[];
  requiredGroups?: RequiredSkillGroup[];
  groupChoices?: Record<string, string[]>;
  onGroupChoiceChange?: (groupKey: string, skillId: string) => void;
  platform: "slack" | "telegram";
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { switchToShared, switchToManual, handlePickShared } = useSharedManualSwitch(
    skillCredentials,
    onSkillCredentialsChange,
  );

  const { skills, total, isLoading } = useSkills({
    search: search || undefined,
    page,
    pageSize: HIRE_DIALOG_PAGE_SIZE,
  });

  const totalPages = Math.max(1, Math.ceil(total / HIRE_DIALOG_PAGE_SIZE));

  const requiredSkillIds = new Set(templateRequiredSkills.map((s) => s.id));
  const groupMemberIds = new Set(requiredGroups.flatMap((g) => g.members.map((m) => m.id)));
  const orderedSkills = [
    ...skills.filter((s) => requiredSkillIds.has(s.id)),
    ...skills.filter((s) => !requiredSkillIds.has(s.id) && !groupMemberIds.has(s.id)),
  ];

  const chosenGroupSkills: TemplateRequiredSkill[] = requiredGroups.flatMap((g) =>
    (groupChoices[g.key] ?? [])
      .map((id) => g.members.find((m) => m.id === id))
      .filter((s): s is TemplateRequiredSkill => !!s),
  );

  // Track full Skill objects for selected skills so we can compute requiredProviders
  // across pages. Users can only toggle visible skills, so this stays in sync.
  const [selectedSkillObjects, setSelectedSkillObjects] = useState<Skill[]>([]);
  const requiredProviderIds: string[] = [
    ...new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...chosenGroupSkills.flatMap((s) => s.requiredProviders),
      ...selectedSkillObjects.flatMap((s) => s.requiredProviders),
    ]),
  ];

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  // Rebuilds skillCredentials to hold exactly one draft per currently-required
  // provider, preserving existing drafts for providers still required and
  // dropping ones that no longer are (e.g. switching a group's choice from
  // GitHub to Bitbucket drops the stale GitHub draft).
  function syncCredentialDrafts(requiredProviders: Set<string>) {
    const newCreds = skillCredentials.filter((c) => requiredProviders.has(c.provider));
    for (const p of requiredProviders) {
      // Auto-configured providers are derived from the agent's configuration and
      // must never appear in the secrets payload.
      if (!isAutoConfiguredProvider(p) && !newCreds.find((c) => c.provider === p)) {
        newCreds.push({ provider: p, content: {} });
      }
    }
    onSkillCredentialsChange(newCreds);
  }

  function toggleSkill(skill: Skill) {
    const isSelected = selectedSkillIds.includes(skill.id);
    const newIds = isSelected
      ? selectedSkillIds.filter((id) => id !== skill.id)
      : [...selectedSkillIds, skill.id];
    const newObjects = isSelected
      ? selectedSkillObjects.filter((s) => s.id !== skill.id)
      : [...selectedSkillObjects, skill];

    const newRequired = new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...chosenGroupSkills.flatMap((s) => s.requiredProviders),
      ...newObjects.flatMap((s) => s.requiredProviders),
    ]);
    syncCredentialDrafts(newRequired);

    onSkillIdsChange(newIds);
    setSelectedSkillObjects(newObjects);
  }

  function toggleGroupMember(groupKey: string, member: TemplateRequiredSkill) {
    const current = groupChoices[groupKey] ?? [];
    const nextIdsForGroup = current.includes(member.id)
      ? current.filter((id) => id !== member.id)
      : [...current, member.id];
    const newChosen = requiredGroups.flatMap((g) =>
      (g.key === groupKey ? nextIdsForGroup : groupChoices[g.key] ?? [])
        .map((id) => g.members.find((m) => m.id === id))
        .filter((s): s is TemplateRequiredSkill => !!s),
    );
    const newRequired = new Set([
      ...templateRequiredSkills.flatMap((s) => s.requiredProviders),
      ...newChosen.flatMap((s) => s.requiredProviders),
      ...selectedSkillObjects.flatMap((s) => s.requiredProviders),
    ]);
    syncCredentialDrafts(newRequired);
    onGroupChoiceChange?.(groupKey, member.id);
  }

  function setField(providerId: string, key: string, value: string) {
    setFields(providerId, { [key]: value });
  }
  /** Apply several keys in ONE update.
   *
   * These helpers derive the next list from the closed-over prop rather than from a
   * functional setState, so successive calls in the same tick all read the same stale
   * value and the last one wins. The OAuth flow writes refreshToken, clientId and
   * clientSecret together, which silently discarded the token. */
  function setFields(providerId: string, patch: Record<string, string>) {
    onSkillCredentialsChange(
      skillCredentials.map((c) =>
        c.provider === providerId
          ? { ...c, content: { ...c.content, ...patch } }
          : c,
      ),
    );
  }

  function setRepos(providerId: string, key: string, repos: string[]) {
    onSkillCredentialsChange(
      skillCredentials.map((c) =>
        c.provider === providerId
          ? { ...c, content: { ...c.content, [key]: repos } }
          : c,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[0.8125rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
        Choose skills to assign to this agent. Required credentials will appear below as you select skills.
      </p>

      {requiredGroups.map((group) => (
        <div key={group.key} className="flex flex-col gap-2">
          <div className="text-[0.8125rem] font-medium" style={{ color: "var(--ink)" }}>
            Required by template — choose at least one
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {group.members.map((member) => {
              const chosen = (groupChoices[group.key] ?? []).includes(member.id);
              return (
                <div
                  key={member.id}
                  role="checkbox"
                  aria-checked={chosen}
                  className="flex flex-col gap-1.5 p-4 rounded-2xl transition-colors min-h-[4.5rem]"
                  style={{
                    cursor: "pointer",
                    border: chosen ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                    background: chosen ? "var(--bg-soft)" : "var(--bg-elev)",
                  }}
                  onClick={() => toggleGroupMember(group.key, member)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                      {member.name}
                    </div>
                    <SkillSourceBadge source={member.source} />
                  </div>
                  <div className="text-[0.6875rem]" style={{ color: "var(--ink-3)" }}>
                    {chosen ? "Selected" : "Required by template"}
                  </div>
                  {member.requiredProviders.length > 0 && (
                    <div className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      {member.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <div
        className="flex items-center gap-2 px-3 py-2 rounded-xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
      >
        <SearchIcon size={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <input
          className="flex-1 text-[0.8125rem] outline-none bg-transparent"
          style={{ color: "var(--ink)" }}
          placeholder="Search skills…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      <div style={isLoading ? { minHeight: "22rem" } : undefined}>
        {isLoading && (
          <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
            Loading skills…
          </div>
        )}
        {!isLoading && total === 0 && !search && (
          <div
            className="text-[0.8125rem] py-6 text-center rounded-2xl"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
          >
            No skills available. Create skills in <strong>Settings → Skills</strong> first.
          </div>
        )}
        {!isLoading && total === 0 && search && (
          <div className="text-[0.8125rem] py-8 text-center" style={{ color: "var(--ink-3)" }}>
            No skills match.
          </div>
        )}
        {!isLoading && skills.length > 0 && (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {orderedSkills.map((skill) => {
              const isRequired = requiredSkillIds.has(skill.id);
              const needsSlackPlatform = skill.requiredProviders.includes("slack") && platform !== "slack";
              const selected = isRequired || selectedSkillIds.includes(skill.id);
              const disabled = !isRequired && needsSlackPlatform;
              return (
                <div
                  key={skill.id}
                  className="flex flex-col gap-1.5 p-4 rounded-2xl transition-colors min-h-[4.5rem]"
                  style={{
                    cursor: isRequired || disabled ? "default" : "pointer",
                    border: selected ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                    background: selected ? "var(--bg-soft)" : "var(--bg-elev)",
                    opacity: disabled ? 0.5 : 1,
                  }}
                  onClick={() => { if (!isRequired && !disabled) toggleSkill(skill); }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                      {skill.name}
                    </div>
                    <SkillSourceBadge source={skill.source} />
                  </div>
                  {isRequired && (
                    <div className="text-[0.6875rem]" style={{ color: "var(--ink-3)" }}>
                      Required by template
                    </div>
                  )}
                  {needsSlackPlatform ? (
                    <div className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                      Requires Slack platform
                    </div>
                  ) : (
                    skill.requiredProviders.length > 0 && (
                      <div className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                        {skill.requiredProviders.map((p) => SKILL_PROVIDER_LABELS[p] ?? p).join(", ")}
                      </div>
                    )
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />

      {requiredProviderIds.length > 0 && (
        <div className="flex flex-col gap-3.5">
          <div className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Required credentials
          </div>
          {requiredProviderIds.map((providerId) => {
            if (providerId === "slack") {
              return (
                <div
                  key={providerId}
                  className="px-4 py-3 rounded-2xl text-[0.8125rem]"
                  style={{ border: "1px solid var(--line)", background: "var(--bg-soft)", color: "var(--ink-3)" }}
                >
                  <span className="font-medium" style={{ color: "var(--ink)" }}>
                    Slack
                  </span>{" "}
                  — uses this agent&apos;s existing Slack bot token automatically. No credentials needed here.
                </div>
              );
            }

            const providerSpec = getIntegrationProvider(providerId);
            const draft = skillCredentials.find((c) => c.provider === providerId);
            if (!draft) return null;

            if (!providerSpec) {
              return (
                <div
                  key={providerId}
                  className="px-4 py-3 rounded-2xl text-[0.8125rem]"
                  style={{ border: "1px solid var(--line)", background: "var(--bg-soft)", color: "var(--ink-3)" }}
                >
                  <span className="font-medium" style={{ color: "var(--ink)" }}>
                    {SKILL_PROVIDER_LABELS[providerId] ?? providerId}
                  </span>{" "}
                  — not yet configurable from the UI.
                </div>
              );
            }

            const isSharedEligible = !!SHARED_CREDENTIAL_PROVIDER_LABELS[providerId];
            const useShared = draft.sharedCredentialId !== undefined;

            return (
              <div
                key={providerId}
                className="flex flex-col gap-3.5 p-4 rounded-2xl"
                style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
              >
                <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>
                  {providerSpec.label}
                  <span
                    className="ml-2 text-[0.6875rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
                    style={{ color: "var(--ink-3)", background: "var(--line)" }}
                  >
                    Required
                  </span>
                </div>

                {isSharedEligible && (
                  <SharedManualToggle
                    provider={providerId}
                    useShared={useShared}
                    selectedId={draft.sharedCredentialId || undefined}
                    onSwitchToManual={() => switchToManual(providerId)}
                    onSwitchToShared={() => switchToShared(providerId)}
                    onPickShared={(brief) => handlePickShared(providerId, brief)}
                  />
                )}

                {!useShared && (
                  <IntegrationFields
                    provider={providerSpec}
                    draft={draft}
                    showScopeNote
                    onFieldChange={(key, value) => setField(providerId, key, value)}
                    onReposChange={(key, repos) => setRepos(providerId, key, repos)}
                    onOAuthConnected={({ refreshToken, clientId, clientSecret }) => {
                      setFields(providerId, { refreshToken, clientId, clientSecret });
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
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

  const { switchToShared, switchToManual, handlePickShared } = useSharedManualSwitch(
    integrations,
    onChange,
  );

  const usedProviders = new Set(integrations.map((i) => i.provider));
  const available = INTEGRATION_PROVIDERS.filter((p) => !usedProviders.has(p.id));

  function addProvider(id: string) {
    onChange([...integrations, { provider: id, content: {} }]);
  }
  function removeProvider(id: string) {
    onChange(integrations.filter((i) => i.provider !== id));
  }
  function setField(providerId: string, key: string, value: string) {
    setFields(providerId, { [key]: value });
  }
  /** Apply several keys in ONE update — see the note on the sibling step: successive
   * single-key calls in the same tick overwrite each other, which dropped the OAuth
   * refresh token. */
  function setFields(providerId: string, patch: Record<string, string>) {
    onChange(
      integrations.map((i) =>
        i.provider === providerId
          ? { ...i, content: { ...i.content, ...patch } }
          : i,
      ),
    );
  }
  function setRepos(providerId: string, key: string, repos: string[]) {
    onChange(
      integrations.map((i) =>
        i.provider === providerId
          ? { ...i, content: { ...i.content, [key]: repos } }
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

      {integrations.map((draft) => {
        const provider = getIntegrationProvider(draft.provider);
        if (!provider) return null;
        const isSharedEligible = !!SHARED_CREDENTIAL_PROVIDER_LABELS[draft.provider];
        const useShared = draft.sharedCredentialId !== undefined;

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

            {isSharedEligible && (
              <SharedManualToggle
                provider={draft.provider}
                useShared={useShared}
                selectedId={draft.sharedCredentialId || undefined}
                onSwitchToManual={() => switchToManual(draft.provider)}
                onSwitchToShared={() => switchToShared(draft.provider)}
                onPickShared={(brief) => handlePickShared(draft.provider, brief)}
              />
            )}

            {!useShared && (
              <IntegrationFields
                provider={provider}
                draft={draft}
                showScopeNote
                onFieldChange={(key, value) => setField(draft.provider, key, value)}
                onReposChange={(key, repos) => setRepos(draft.provider, key, repos)}
                onOAuthConnected={({ refreshToken, clientId, clientSecret }) => {
                  setFields(draft.provider, { refreshToken, clientId, clientSecret });
                }}
              />
            )}
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
