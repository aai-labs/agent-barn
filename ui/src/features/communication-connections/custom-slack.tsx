import type { CommunicationPlatform } from "./schemas";

/** Custom Slack is a Slack Connection whose `apiUrl` names a self-hosted, Slack-compatible
 * server. It is a UI choice only: the API stores it as the one Slack Connection. */
export const CUSTOM_SLACK_NAME = "Custom Slack";

const SETUP_HINT =
  "1. Ask the chat's administrator for its **Slack API address** and the bot's `xoxb-` and `xapp-` tokens.\n" +
  "2. Have them add the bot to every channel it should handle.";

type Schema = Record<string, unknown>;

/** Only a Hermes Agent's own runtime can point Slack at a Custom Slack server; the API refuses the rest. */
export function offersCustomSlack(agent: { agentType: string; parentAgentId: string | null }): boolean {
  return agent.agentType === "hermes" && !agent.parentAgentId;
}

export function isCustomSlack(connection: { platformKey: string; settings: Record<string, unknown> }): boolean {
  return connection.platformKey === "slack" && Boolean(connection.settings.apiUrl);
}

export function hasServerAddress(settings: Record<string, unknown>): boolean {
  return Boolean(String(settings.apiUrl ?? "").trim());
}

export function serverHost(url: unknown): string {
  try {
    return new URL(String(url)).host;
  } catch {
    return String(url ?? "");
  }
}

/** The settings schema without the server address, which only Custom Slack shows, on its own. */
export function withoutServerAddress(schema: Schema): Schema {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object" || !("apiUrl" in properties)) return schema;
  const rest = { ...(properties as Schema) };
  delete rest.apiUrl;
  return { ...schema, properties: rest };
}

/** Slack's credential hints describe a slack.com app; a Custom Slack server's administrator issues both tokens. */
function issuedCredentials(schema: Schema): Schema {
  const properties = schema.properties as Record<string, Schema> | undefined;
  if (!properties) return schema;
  const issued = (prefix: string) => `Starts with ${prefix}. Issued by the chat's administrator.`;
  return {
    ...schema,
    properties: {
      ...properties,
      ...(properties.botToken && { botToken: { ...properties.botToken, description: issued("xoxb-") } }),
      ...(properties.appToken && { appToken: { ...properties.appToken, description: issued("xapp-") } }),
    },
  };
}

/** What the add and edit forms show for a platform, resolved once instead of per field. */
export type ConnectionForm = {
  custom: boolean;
  name: string;
  description: string;
  setupHint: string | null | undefined;
  manifest: object | null;
  credentialsSchema: Schema;
  settingsSchema: Schema;
};

export function connectionForm(
  platform: CommunicationPlatform,
  { custom, manifest }: { custom: boolean; manifest: object | null },
): ConnectionForm {
  const settingsSchema = withoutServerAddress(platform.settingsSchema);
  if (!custom) {
    return {
      custom,
      name: platform.displayName,
      description: "Add its credentials first, then name the connection and choose where it listens.",
      setupHint: platform.setupHint,
      manifest,
      credentialsSchema: platform.credentialsSchema,
      settingsSchema,
    };
  }
  return {
    custom,
    name: CUSTOM_SLACK_NAME,
    description: "Connect a self-hosted chat that speaks Slack's bot API, such as Chatty.",
    setupHint: SETUP_HINT,
    manifest: null,
    credentialsSchema: issuedCredentials(platform.credentialsSchema),
    settingsSchema,
  };
}

export function ServerAddressInput({ value, onChange }: { value: unknown; onChange: (value: string) => void }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium">
      Server address *
      <input
        className="af-input"
        type="url"
        inputMode="url"
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
        placeholder="https://chat.example.com/slack/api/"
      />
      <span className="text-xs font-normal" style={{ color: "var(--ink-4)" }}>
        The chat&apos;s Slack API address. Must be a public https address.
      </span>
    </label>
  );
}
