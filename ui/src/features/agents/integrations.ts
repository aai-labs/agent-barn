// Provider field spec driving the hire-wizard "Integrations" step.
//
// `provider` ids are the backend SecretProvider enum VALUES (sent as-is — humps
// does not transform values). Field `key`s are camelCase and are decamelized to
// the backend content schema's snake_case fields by the axios request interceptor
// (e.g. `siteUrl` -> `site_url`, `apiToken` -> `api_token`). Constant infra fields
// (smtp/imap host+port, folders, …) are NOT inputs here — the backend fills them
// as schema defaults.

export type IntegrationFieldType = "text" | "secret";

export interface IntegrationField {
  key: string;
  label: string;
  type: IntegrationFieldType;
  required: boolean;
  placeholder?: string;
  hint?: string;
}

export interface IntegrationProvider {
  id: string;
  label: string;
  fields: IntegrationField[];
}

export interface IntegrationDraft {
  provider: string;
  content: Record<string, string>;
}

export const INTEGRATION_PROVIDERS: IntegrationProvider[] = [
  {
    id: "github",
    label: "GitHub",
    fields: [
      { key: "token", label: "Personal access token", type: "secret", required: true, placeholder: "github_pat_… or ghp_…" },
      { key: "owner", label: "Owner", type: "text", required: true, placeholder: "repo owner" },
      { key: "repo", label: "Repository", type: "text", required: true, placeholder: "repository" },
      { key: "org", label: "Organization", type: "text", required: true, placeholder: "organization" },
    ],
  },
  {
    id: "jira",
    label: "Jira",
    fields: [
      { key: "siteUrl", label: "Site URL", type: "text", required: true, placeholder: "https://your-domain.atlassian.net" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "confluence",
    label: "Confluence",
    fields: [
      { key: "siteUrl", label: "Site URL", type: "text", required: true, placeholder: "https://your-domain.atlassian.net" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "bitbucket",
    label: "Bitbucket",
    fields: [
      { key: "workspace", label: "Workspace", type: "text", required: true, placeholder: "workspace id" },
      { key: "repo", label: "Repository", type: "text", required: true, placeholder: "repository" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "gmail",
    label: "Gmail",
    fields: [
      { key: "accessToken", label: "Access token", type: "secret", required: true },
      { key: "userId", label: "User ID", type: "text", required: true, placeholder: "me" },
    ],
  },
  {
    id: "google_calendar",
    label: "Google Calendar",
    fields: [
      { key: "accessToken", label: "Access token", type: "secret", required: true },
      { key: "calendarId", label: "Calendar ID", type: "text", required: true, placeholder: "primary" },
    ],
  },
  {
    id: "zoho_mail",
    label: "Zoho Mail",
    fields: [
      { key: "username", label: "Username", type: "text", required: true, placeholder: "you@zoho.com" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@zoho.com" },
      { key: "fromAddress", label: "From address", type: "text", required: true, placeholder: "you@zoho.com" },
      { key: "appPassword", label: "App password", type: "secret", required: true },
    ],
  },
  {
    id: "zoho_calendar",
    label: "Zoho Calendar",
    fields: [
      { key: "username", label: "Username", type: "text", required: true, placeholder: "you@zoho.com" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@zoho.com" },
      { key: "appPassword", label: "App password", type: "secret", required: true },
      { key: "caldavUrl", label: "CalDAV URL", type: "text", required: true, placeholder: "https://calendar.zoho.com/…" },
    ],
  },
];

export function getIntegrationProvider(id: string): IntegrationProvider | undefined {
  return INTEGRATION_PROVIDERS.find((p) => p.id === id);
}

// True if any added integration is missing a required field — used to gate "Hire".
export function hasIncompleteIntegration(integrations: IntegrationDraft[]): boolean {
  return integrations.some((draft) => {
    const provider = getIntegrationProvider(draft.provider);
    if (!provider) return true;
    return provider.fields.some(
      (f) => f.required && !(draft.content[f.key] ?? "").trim(),
    );
  });
}
