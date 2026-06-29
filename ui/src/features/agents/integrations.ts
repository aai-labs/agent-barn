// Provider field spec driving the hire-wizard "Integrations" step.
//
// `provider` ids are the backend SecretProvider enum VALUES (sent as-is — humps
// does not transform values). Field `key`s are camelCase and are decamelized to
// the backend content schema's snake_case fields by the axios request interceptor
// (e.g. `siteUrl` -> `site_url`, `apiToken` -> `api_token`). Constant infra fields
// (smtp/imap host+port, folders, …) are NOT inputs here — the backend fills them
// as schema defaults.

export type IntegrationFieldType = "text" | "secret" | "repo-url";

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
  scopeNote?: string;
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
    scopeNote: "Classic PAT: repo, read:user, read:org — Fine-grained PAT: Contents (read), Pull requests (read + write), Metadata (read, mandatory)",
    fields: [
      { key: "token", label: "Personal access token", type: "secret", required: true, placeholder: "github_pat_… or ghp_…" },
      { key: "repoUrl", label: "Repository URL", type: "repo-url", required: true, placeholder: "https://github.com/owner/repo.git" },
    ],
  },
  {
    id: "jira",
    label: "Jira",
    scopeNote: "API token inherits your Atlassian account's project permissions — account needs Browse Projects and Add Comments on the target project",
    fields: [
      { key: "siteUrl", label: "Site URL", type: "text", required: true, placeholder: "https://your-domain.atlassian.net" },
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
      { key: "repo", label: "Repository", type: "text", required: true, placeholder: "repository" },
      { key: "email", label: "Email", type: "text", required: true, placeholder: "you@example.com" },
      { key: "apiToken", label: "API token", type: "secret", required: true },
    ],
  },
];

export function getIntegrationProvider(id: string): IntegrationProvider | undefined {
  return INTEGRATION_PROVIDERS.find((p) => p.id === id);
}

export function parseGithubRepoUrl(url: string): { owner: string; repo: string } | null {
  const m = url.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?$/);
  return m ? { owner: m[1], repo: m[2] } : null;
}

export function expandGithubContent(content: Record<string, string>): Record<string, string> {
  const parsed = parseGithubRepoUrl(content.repoUrl ?? "");
  if (!parsed) return content;
  const { owner, repo } = parsed;
  const { repoUrl: _, ...rest } = content;
  return { ...rest, owner, repo, org: owner };
}

// True if any added integration is missing a required field — used to gate "Hire".
export function hasIncompleteIntegration(integrations: IntegrationDraft[]): boolean {
  return integrations.some((draft) => {
    const provider = getIntegrationProvider(draft.provider);
    if (!provider) return true;
    return provider.fields.some((f) => {
      if (!f.required) return false;
      const value = (draft.content[f.key] ?? "").trim();
      if (!value) return true;
      if (f.type === "repo-url") return parseGithubRepoUrl(value) === null;
      return false;
    });
  });
}
