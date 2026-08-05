import { createQueryKeyStructure } from "@/shared/query-keys";

export const sharedCredentialsKey = createQueryKeyStructure("shared-credentials");
export const SHARED_CREDENTIALS_PAGE_SIZE = 15;

export const SHARED_CREDENTIAL_PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  jira: "Jira",
  confluence: "Confluence",
  bitbucket: "Bitbucket",
  zoho_mail: "Zoho Mail",
};

export const SHARED_CREDENTIAL_PROVIDERS = Object.entries(
  SHARED_CREDENTIAL_PROVIDER_LABELS,
).map(([value, label]) => ({ value, label }));
