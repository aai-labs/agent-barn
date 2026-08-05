// Provider field spec driving the hire-wizard "Integrations" step.
//
// `provider` ids are the backend SecretProvider enum VALUES (sent as-is — humps
// does not transform values). Field `key`s are camelCase and are decamelized to
// the backend content schema's snake_case fields by the axios request interceptor
// (e.g. `siteUrl` -> `site_url`, `apiToken` -> `api_token`). Constant infra fields
// (smtp/imap host+port, folders, …) are NOT inputs here — the backend fills them
// as schema defaults.

export type IntegrationFieldType = "text" | "secret" | "repo-list" | "radio";

export interface IntegrationField {
  key: string;
  label: string;
  type: IntegrationFieldType;
  options?: { label: string; value: string }[];
  dependsOn?: { key: string; value: string };
  required: boolean;
  placeholder?: string;
  hint?: string;
}

export interface IntegrationProvider {
  id: string;
  label: string;
  scopeNote?: string;
  fields: IntegrationField[];
  // When set, the provider is configured via an OAuth flow (an "Authenticate with
  // <provider>" button) instead of manual field entry. "google_oauth" captures a
  // refresh token via the popup flow and writes it to content.refreshToken; the
  // provider id selects which scopes Google is asked for.
  authMethod?: "google_oauth";
  // Shown next to the ✓ once an OAuth provider is connected — describes the access
  // that was actually granted.
  oauthConnectedNote?: string;
}

export interface IntegrationDraft {
  provider: string;
  content: Record<string, string | string[]>;
  sharedCredentialId?: string;
}

export const INTEGRATION_PROVIDERS: IntegrationProvider[] = [
  {
    id: "github",
    label: "GitHub",
    scopeNote: "Classic PAT: repo, read:user, read:org — Fine-grained PAT: Contents (read), Pull requests (read + write), Metadata (read, mandatory)",
    fields: [
      { key: "token", label: "Personal access token", type: "secret", required: true, placeholder: "github_pat_… or ghp_…" },
      { key: "owner", label: "Owner / Org", type: "text", required: true, placeholder: "owner-or-org" },
      { key: "repos", label: "Repositories", type: "repo-list", required: false, placeholder: "repository name", hint: "Leave empty to allow access to any repository the token can reach — the agent will need to pass a repo name explicitly." },
    ],
  },
  {
    id: "jira",
    label: "Jira",
    scopeNote: "API token inherits your Atlassian account's project permissions — account needs Browse Projects and Add Comments on the target project",
    fields: [
      { key: "siteUrl", label: "Site URL", type: "text", required: true, placeholder: "https://your-domain.atlassian.net" },
      {
        key: "useScopedToken",
        label: "Authentication Type",
        type: "radio",
        required: true,
        options: [
          { label: "Non-scoped token", value: "false" },
          { label: "Scoped token", value: "true" }
        ]
      },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "confluence",
    label: "Confluence",
    scopeNote: "API token inherits your Atlassian account's space permissions — account needs Space View and Add Page Comments on the target space",
    fields: [
      { key: "siteUrl", label: "Site URL", type: "text", required: true, placeholder: "https://your-domain.atlassian.net" },
      {
        key: "useScopedToken",
        label: "Authentication Type",
        type: "radio",
        required: true,
        options: [
          { label: "Non-scoped token", value: "false" },
          { label: "Scoped token", value: "true" }
        ]
      },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "bitbucket",
    label: "Bitbucket",
    scopeNote: "App password scopes: Account (read), Repositories (read), Pull requests (read + write)",
    fields: [
      { key: "workspace", label: "Workspace", type: "text", required: true, placeholder: "workspace id" },
      { key: "repos", label: "Repositories", type: "repo-list", required: false, placeholder: "repository name", hint: "Leave empty to allow access to any repository the token can reach — the agent will need to pass a repo name explicitly." },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
  {
    id: "gmail",
    label: "Gmail",
    authMethod: "google_oauth",
    scopeNote: "Read-only Gmail access via Google sign-in (gmail.readonly). No manual keys needed.",
    oauthConnectedNote: "read-only Gmail access granted",
    fields: [],
  },
  {
    id: "google_sheets",
    label: "Google Sheets",
    authMethod: "google_oauth",
    scopeNote:
      "Read and write spreadsheet values via Google sign-in (spreadsheets), plus metadata-only Drive access to list your spreadsheets. No manual keys needed.",
    oauthConnectedNote: "read/write access to your spreadsheets granted",
    fields: [],
  },
  // google_calendar disabled: not currently offered as an integration. Re-enable by
  // uncommenting once it's wired up (e.g. behind the Google OAuth flow like gmail).
  // {
  //   id: "google_calendar",
  //   label: "Google Calendar",
  //   scopeNote: "OAuth2 access token with calendar.readonly or calendar scope",
  //   fields: [
  //     { key: "accessToken", label: "Access token", type: "secret", required: true },
  //     { key: "calendarId", label: "Calendar ID", type: "text", required: true, placeholder: "primary or calendar@group.calendar.google.com" },
  //   ],
  // },
  {
    id: "zoho_mail",
    label: "Zoho Mail",
    scopeNote: "OAuth 2.0 client credentials with ZohoMail.messages.READ scope",
    fields: [
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@yourdomain.com", hint: "Zoho Mail account email address" },
      { key: "accountId", label: "Account ID", type: "text", required: true, placeholder: "56218000000008002", hint: "Zoho Mail account ID (from API console)" },
      { key: "clientId", label: "Client ID", type: "text", required: true, placeholder: "1000.…", hint: "Zoho OAuth 2.0 client ID" },
      { key: "clientSecret", label: "Client secret", type: "secret", required: true, hint: "Zoho OAuth 2.0 client secret" },
      { key: "refreshToken", label: "Refresh token", type: "secret", required: true, hint: "OAuth 2.0 refresh token for the Zoho Mail account" },
    ],
  },
  {
    id: "firecrawl",
    label: "Firecrawl",
    scopeNote: "Optional — agents use the platform Firecrawl by default. Provide your own API key and URL to use Firecrawl Cloud or another instance.",
    fields: [
      { key: "apiKey", label: "API key", type: "secret", required: true, placeholder: "fc-…" },
      { key: "baseUrl", label: "Base URL", type: "text", required: false, placeholder: "https://api.firecrawl.dev", hint: "Leave empty to use the platform's self-hosted Firecrawl." },
    ],
  },
  {
    id: "pipedrive",
    label: "Pipedrive",
    scopeNote: "Personal API token grants full account access — no scopes to select. Domain is optional; only needed for a custom Pipedrive endpoint.",
    fields: [
      { key: "apiToken", label: "API token", type: "secret", required: true },
      { key: "domain", label: "Company domain", type: "text", required: false, placeholder: "aai-labs", hint: "Leave empty to use the default api.pipedrive.com endpoint." },
    ],
  },
  // zoho_calendar disabled: not currently offered as an integration. Re-enable by
  // uncommenting if needed again.
  // {
  //   id: "zoho_calendar",
  //   label: "Zoho Calendar",
  //   scopeNote: "App password from Zoho account security settings (two-factor must be enabled)",
  //   fields: [
  //     { key: "username", label: "Username", type: "text", required: true, placeholder: "you@zoho.com" },
  //     { key: "email", label: "Email", type: "text", required: true, placeholder: "you@zoho.com" },
  //     { key: "appPassword", label: "App password", type: "secret", required: true },
  //     { key: "caldavUrl", label: "CalDAV URL", type: "text", required: true, placeholder: "https://calendar.zoho.com/caldav/..." },
  //   ],
  // },
];

export function getIntegrationProvider(id: string): IntegrationProvider | undefined {
  return INTEGRATION_PROVIDERS.find((p) => p.id === id);
}

export function expandGithubContent(
  content: Record<string, string | string[]>,
): Record<string, string | string[]> {
  const owner = typeof content.owner === "string" ? content.owner : "";
  const repos = Array.isArray(content.repos) ? content.repos : [];
  return { ...content, owner, org: owner, repos };
}

// Field keys backed by a real `bool` on the API content model, even though the
// "radio" control can only emit the strings "true"/"false" (see IntegrationField.type).
// The axios request interceptor decamelizes keys but leaves values untouched, so this
// is the one place these get converted back to real booleans before submission.
const BOOLEAN_FIELD_KEYS = new Set(["useScopedToken"]);

export function coerceBooleanFields(
  content: Record<string, string | string[]>,
): Record<string, string | string[] | boolean> {
  const coerced: Record<string, string | string[] | boolean> = { ...content };
  for (const key of BOOLEAN_FIELD_KEYS) {
    if (key in coerced) {
      coerced[key] = coerced[key] === "true";
    }
  }
  return coerced;
}

// True if the OAuth-based provider hasn't captured its refresh token yet.
export function isOAuthConnected(draft: IntegrationDraft): boolean {
  const token = draft.content.refreshToken;
  return typeof token === "string" && token.trim().length > 0;
}

// True if any added integration is missing a required field — used to gate "Hire".
export function hasIncompleteIntegration(integrations: IntegrationDraft[]): boolean {
  return integrations.some((draft) => {
    if (draft.sharedCredentialId) return false;
    const provider = getIntegrationProvider(draft.provider);
    if (!provider) return true;
    // OAuth providers have no manual fields; they're complete once connected.
    if (provider.authMethod === "google_oauth") return !isOAuthConnected(draft);
    return provider.fields.some((f) => {
      if (!f.required) return false;
      
      // If the field depends on another field, check if the condition is met
      if (f.dependsOn) {
        const dependentValue = draft.content[f.dependsOn.key];
        if (dependentValue !== f.dependsOn.value) {
            return false; // Skip validation since this field is not active
        }
      }

      const value = draft.content[f.key];
      return typeof value !== "string" || value.trim().length === 0;
    });
  });
}
