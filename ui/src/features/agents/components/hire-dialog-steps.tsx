"use client";

import { useState } from "react";
import JSZip from "jszip";
import { TEMPLATE_FILES } from "../data";
import { ChoiceCard, FormField, NextStep, TokenInput } from "./hire-dialog-primitives";

export const ROLES = [
  { id: "default", template_id: "t_default", title: "General Purpose", emoji: "🤖", tagline: "Answers questions, handles tasks, reduces day-to-day friction.", suggested: "Aria" },
  { id: "code-reviewer", template_id: "t_reviewer", title: "PR Reviewer", emoji: "⚙️", tagline: "Reads diffs, comments on style, security, and tests.", suggested: "Halo" },
  { id: "analyst", template_id: "t_analyst", title: "Data Analyst", emoji: "📊", tagline: "Answers questions over BigQuery & Sheets, returns charts.", suggested: "Lyra" },
  { id: "sales-research", template_id: "t_sales", title: "Sales Research", emoji: "📈", tagline: "Enriches leads, drafts outbound, summarises calls.", suggested: "Vega" },
] as const;

export type RoleId = (typeof ROLES)[number]["id"];
export type WizardStep =
  | "role"
  | "platform-choice"
  | "slack-choice"
  | "bot-builder"
  | "slack-tokens"
  | "teams-bot-builder"
  | "teams-credentials"
  | "details";

export const MODELS = [{ value: "litellm/gpt-5-mini", label: "GPT-5 mini" }] as const;

export const BOT_COLOR_PRESETS = ["#4A154B", "#1264A3", "#2BAC76", "#E8912D", "#CC4400"];
const TEAMS_DEVELOPER_NAME = "Agent Farm";
const TEAMS_DEVELOPER_WEBSITE_URL = "https://example.com";
const TEAMS_PRIVACY_URL = "https://example.com/privacy";
const TEAMS_TERMS_URL = "https://example.com/terms";

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

export function pickDefaults(roleId: RoleId) {
  const role = ROLES.find((r) => r.id === roleId)!;
  const tpl = TEMPLATE_FILES[role.template_id] ?? {};
  return {
    name: role.suggested,
    botName: role.suggested,
    botDescription: role.tagline,
    soulMd: tpl.soul_md ?? "",
    identityMd: tpl.identity_md ?? "",
    userMd: tpl.user_md ?? "",
    toolsMd: tpl.tools_md ?? "",
  };
}

function generateManifest(name: string, description: string, color: string): string {
  return JSON.stringify(
    {
      display_information: { name, description, background_color: color },
      features: {
        app_home: {
          home_tab_enabled: false,
          messages_tab_enabled: true,
          messages_tab_read_only_enabled: false,
        },
        bot_user: { display_name: name, always_online: true },
      },
      oauth_config: {
        scopes: {
          bot: [
            "app_mentions:read",
            "channels:history",
            "channels:join",
            "channels:read",
            "chat:write",
            "chat:write.public",
            "groups:history",
            "groups:read",
            "im:history",
            "im:read",
            "im:write",
            "mpim:history",
            "mpim:read",
            "mpim:write",
            "reactions:read",
            "reactions:write",
            "users:read",
            "users:read.email",
          ],
        },
      },
      settings: {
        event_subscriptions: {
          bot_events: [
            "app_mention",
            "message.channels",
            "message.groups",
            "message.im",
            "message.mpim",
          ],
        },
        interactivity: { is_enabled: true },
        org_deploy_enabled: false,
        socket_mode_enabled: true,
        token_rotation_enabled: false,
      },
    },
    null,
    2,
  );
}

export function RoleStep({ pick, onPick }: { pick: RoleId; onPick: (id: RoleId) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      {ROLES.map((r) => (
        <div
          key={r.id}
          className="flex flex-col gap-2 p-4 rounded-2xl cursor-default transition-colors"
          style={{
            border: pick === r.id ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
            background: pick === r.id ? "var(--bg-soft)" : "var(--bg-elev)",
          }}
          onClick={() => onPick(r.id)}
        >
          <div className="text-2xl">{r.emoji}</div>
          <div className="font-semibold text-[0.844rem]" style={{ color: "var(--ink)" }}>{r.title}</div>
          <div className="text-[0.781rem] leading-[1.4]" style={{ color: "var(--ink-3)" }}>{r.tagline}</div>
        </div>
      ))}
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
        selected={!setupNewBot}
        onClick={() => onChange(false)}
        title="I already have a Slack app"
        description="Skip straight to entering your app and bot tokens."
      />
      <ChoiceCard
        selected={setupNewBot}
        onClick={() => onChange(true)}
        title="Set up a new Slack bot"
        description="We'll generate a manifest so you can create one in seconds."
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
  const [copied, setCopied] = useState(false);
  const manifest = generateManifest(botName, botDescription, botColor);

  function copyManifest() {
    void navigator.clipboard.writeText(manifest).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function downloadManifest() {
    const blob = new Blob([manifest], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${botName.toLowerCase().replace(/\s+/g, "-")}-manifest.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

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

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
            Teams app package
          </span>
          <div className="flex gap-1.5">
            <button className="af-btn af-btn-sm" onClick={copyManifest}>
              {copied ? "Copied!" : "Copy"}
            </button>
            <button className="af-btn af-btn-sm" onClick={downloadManifest}>
              Download
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
        <NextStep n={1} label="Create your Slack app from this manifest">
          Copy the manifest above, then click the link to open Slack&apos;s app creation page.
          Choose <b>From an app manifest</b>, paste it in, and create the app.{" "}
          <a
            href="https://api.slack.com/apps?new_app=1"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            Create app ↗
          </a>
        </NextStep>
        <NextStep n={2} label="Install the app to your workspace">
          In your new app&apos;s settings, go to <b>Install App</b> and click{" "}
          <b>Install to workspace</b>. Slack will generate a{" "}
          <span className="font-mono text-xs">xoxb-…</span> bot token automatically.{" "}
          <a
            href="https://api.slack.com/apps"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            Your apps ↗
          </a>
        </NextStep>
        <NextStep n={3} label="Create an App-Level Token">
          Go to <b>Basic Information</b> → <b>App-Level Tokens</b> → <b>Generate Token</b>.
          Name it anything and add the <span className="font-mono text-xs">connections:write</span> scope.
          This creates your <span className="font-mono text-xs">xapp-…</span> token, required for Socket Mode.{" "}
          <a
            href="https://api.slack.com/apps"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            style={{ color: "var(--ink-2)" }}
          >
            Your apps ↗
          </a>
        </NextStep>
        <NextStep n={4} label="Come back and enter both tokens">
          You&apos;ll paste them on the next screen.
        </NextStep>
      </div>
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
}) {
  return (
    <div className="flex flex-col gap-5">
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
    </div>
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
        description="Connect via Socket Mode with a bot and app-level token."
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
            Generated manifest
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
    <div className="flex flex-col gap-5">
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
    </div>
  );
}

export function DetailsStep({
  selected,
  platform,
  name,
  onNameChange,
  model,
  onModelChange,
  slackGroupPolicy,
  onSlackGroupPolicyChange,
  slackDmPolicy,
  onSlackDmPolicyChange,
  soulMd,
  onSoulMdChange,
  identityMd,
  onIdentityMdChange,
  userMd,
  onUserMdChange,
  toolsMd,
  onToolsMdChange,
  onChangeRole,
}: {
  selected: (typeof ROLES)[number];
  platform: "slack" | "teams";
  name: string;
  onNameChange: (v: string) => void;
  model: string;
  onModelChange: (v: string) => void;
  slackGroupPolicy: string;
  onSlackGroupPolicyChange: (v: string) => void;
  slackDmPolicy: string;
  onSlackDmPolicyChange: (v: string) => void;
  soulMd: string;
  onSoulMdChange: (v: string) => void;
  identityMd: string;
  onIdentityMdChange: (v: string) => void;
  userMd: string;
  onUserMdChange: (v: string) => void;
  toolsMd: string;
  onToolsMdChange: (v: string) => void;
  onChangeRole: () => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div
        className="flex items-center gap-3 p-4 rounded-2xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="text-2xl">{selected.emoji}</div>
        <div className="flex-1">
          <div className="font-semibold text-sm" style={{ color: "var(--ink)" }}>{selected.title}</div>
          <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>{selected.tagline}</div>
        </div>
        <button className="af-btn af-btn-sm af-btn-ghost" onClick={onChangeRole}>Change</button>
      </div>

      <FormField label="Name them" hint={`Suggested: ${selected.suggested}`}>
        <input
          className="af-input af-input-lg"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder={selected.suggested}
        />
      </FormField>

      <FormField label="Model">
        <select
          className="af-input"
          aria-label="Model"
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
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
              <option value="pairing">Pairing — users must pair first</option>
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
        <div className="p-4 flex flex-col gap-4" style={{ background: "var(--bg-soft)" }}>
          <div className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
            Pre-populated from the <span className="font-mono">{selected.id}</span> template. Edit before hiring to customise.
          </div>
          <FormField label="soul.md" hint="Core purpose and values — required">
            <textarea className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none" rows={7} value={soulMd} onChange={(e) => onSoulMdChange(e.target.value)} />
          </FormField>
          <FormField label="identity.md" hint="Voice, tone, and hard boundaries — required">
            <textarea className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none" rows={7} value={identityMd} onChange={(e) => onIdentityMdChange(e.target.value)} />
          </FormField>
          <FormField label="user.md" hint="Who this agent talks to">
            <textarea className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none" rows={5} value={userMd} onChange={(e) => onUserMdChange(e.target.value)} />
          </FormField>
          <FormField label="tools.md" hint="Available tools">
            <textarea className="af-input font-mono text-[0.781rem] leading-[1.65] resize-none" rows={5} value={toolsMd} onChange={(e) => onToolsMdChange(e.target.value)} />
          </FormField>
        </div>
      </details>
    </div>
  );
}
