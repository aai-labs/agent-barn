import { createQueryKeyStructure } from "@/shared/query-keys";

export const skillsKey = createQueryKeyStructure("skills");
export const SKILLS_PAGE_SIZE = 15;

export const SKILL_PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  jira: "Jira",
  confluence: "Confluence",
  bitbucket: "Bitbucket",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
  zoho_mail: "Zoho Mail",
  zoho_calendar: "Zoho Calendar",
};

export const ALL_PROVIDERS = Object.entries(SKILL_PROVIDER_LABELS).map(
  ([value, label]) => ({ value, label }),
);

export async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
  });
}