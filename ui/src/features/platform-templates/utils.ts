import { createQueryKeyStructure } from "@/shared/query-keys";

export const platformTemplatesKey = createQueryKeyStructure("platform-templates");
export const platformTemplatePublishedKey = createQueryKeyStructure("platform-template-published");
export const platformTemplateVersionsKey = createQueryKeyStructure("platform-template-versions");

export const PLATFORM_TEMPLATE_FILES = [
  { key: "soulMd", label: "SOUL.md" },
  { key: "identityMd", label: "IDENTITY.md" },
  { key: "userMd", label: "USER.md" },
  { key: "toolsMd", label: "TOOLS.md" },
  { key: "agentsMd", label: "AGENTS.md" },
  { key: "bootMd", label: "BOOT.md" },
  { key: "bootstrapMd", label: "BOOTSTRAP.md" },
  { key: "heartbeatMd", label: "HEARTBEAT.md" },
] as const;

export type PlatformTemplateFileKey = (typeof PLATFORM_TEMPLATE_FILES)[number]["key"];

export type PlatformTemplateFileValues = Record<PlatformTemplateFileKey, string>;

export type SkillGroupDraft = {
  groupKey: string;
  skillIds: string[];
};

export type PlatformTemplateForm = {
  templateName: string;
  description: string;
  files: PlatformTemplateFileValues;
  standaloneSkillIds: string[];
  skillGroups: SkillGroupDraft[];
};

export function blankPlatformTemplateFiles(): PlatformTemplateFileValues {
  return Object.fromEntries(
    PLATFORM_TEMPLATE_FILES.map(({ key }) => [key, ""]),
  ) as PlatformTemplateFileValues;
}

export function formFromDraft(draft: {
  templateName: string;
  description: string | null;
  soulMd: string;
  identityMd: string;
  userMd: string;
  toolsMd: string;
  agentsMd: string;
  bootMd: string;
  bootstrapMd: string;
  heartbeatMd: string;
  requiredSkills: Array<{ id: string; groupKey?: string | null }>;
}): PlatformTemplateForm {
  const grouped = new Map<string, string[]>();
  const standaloneSkillIds: string[] = [];

  for (const skill of draft.requiredSkills) {
    if (skill.groupKey) {
      grouped.set(skill.groupKey, [...(grouped.get(skill.groupKey) ?? []), skill.id]);
    } else {
      standaloneSkillIds.push(skill.id);
    }
  }

  return {
    templateName: draft.templateName,
    description: draft.description ?? "",
    files: {
      soulMd: draft.soulMd,
      identityMd: draft.identityMd,
      userMd: draft.userMd,
      toolsMd: draft.toolsMd,
      agentsMd: draft.agentsMd,
      bootMd: draft.bootMd,
      bootstrapMd: draft.bootstrapMd,
      heartbeatMd: draft.heartbeatMd,
    },
    standaloneSkillIds,
    skillGroups: Array.from(grouped, ([groupKey, skillIds]) => ({ groupKey, skillIds })),
  };
}

export function requiredSkillPayload(form: PlatformTemplateForm) {
  return {
    requiredSkillIds: form.standaloneSkillIds,
    requiredSkillGroups: form.skillGroups.filter((group) => group.skillIds.length > 0),
  };
}
