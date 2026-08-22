import type { PlatformTemplateFileKey } from "@/features/platform-templates/utils";

import type {
  AgentConfigurationVersion,
  AgentOverrideDraft,
  AgentOverrideVersion,
  AgentTemplateRead,
} from "../schemas";

export type ArtifactKey = PlatformTemplateFileKey;
export type ConfigurationSnapshot =
  | AgentConfigurationVersion
  | AgentOverrideDraft
  | AgentOverrideVersion;
export type Snapshot = ConfigurationSnapshot | AgentTemplateRead;
export type AgentConfigurationSectionKey =
  | "profile"
  | "template"
  | "channels"
  | "skills"
  | "keys"
  | "override"
  | "danger";

export type AgentConfigurationSection = {
  key: AgentConfigurationSectionKey;
  label: string;
  description: string;
};

export const AGENT_CONFIGURATION_SECTIONS: AgentConfigurationSection[] = [
  {
    key: "profile",
    label: "Profile",
    description: "Identity, runtime, and deployment facts for this Agent.",
  },
  {
    key: "template",
    label: "Template selection",
    description: "Inspect any published shared or Agent-owned version and apply it with a restart.",
  },
  {
    key: "channels",
    label: "Channels & endpoint",
    description: "Where this Agent receives messages and sends replies.",
  },
  {
    key: "skills",
    label: "Skills",
    description: "Assigned tools and the credentials they require.",
  },
  {
    key: "keys",
    label: "Keys & integrations",
    description: "Platform tokens and encrypted integration credentials.",
  },
  {
    key: "override",
    label: "Agent-owned override",
    description: "Draft, edit, and publish a private template snapshot.",
  },
  {
    key: "danger",
    label: "Danger zone",
    description: "Irreversible lifecycle actions.",
  },
];

export function configurationSectionLabel(
  key: AgentConfigurationSectionKey,
): string {
  return AGENT_CONFIGURATION_SECTIONS.find((section) => section.key === key)?.label ?? key;
}

export type RequiredSkillGroupDraft = { groupKey: string; skillIds: string[] };
export type DraftTextField = ArtifactKey | "description" | "templateName";
export type DraftForm = Record<ArtifactKey, string> & {
  description: string;
  templateName: string;
  requiredSkillIds: string[];
  requiredSkillGroups: RequiredSkillGroupDraft[];
};

export type AgentConfigurationEditHandle = {
  apply: () => Promise<void>;
  cancel: () => void;
};

export function draftToForm(draft: AgentOverrideDraft): DraftForm {
  const requiredSkillIds = draft.requiredSkills
    .filter((skill) => !skill.groupKey)
    .map((skill) => skill.id);
  const groups = new Map<string, string[]>();
  for (const skill of draft.requiredSkills) {
    if (skill.groupKey) {
      groups.set(skill.groupKey, [
        ...(groups.get(skill.groupKey) ?? []),
        skill.id,
      ]);
    }
  }

  return {
    templateName: draft.templateName,
    description: draft.description ?? "",
    soulMd: draft.soulMd,
    identityMd: draft.identityMd,
    userMd: draft.userMd,
    toolsMd: draft.toolsMd,
    agentsMd: draft.agentsMd,
    bootMd: draft.bootMd,
    bootstrapMd: draft.bootstrapMd,
    heartbeatMd: draft.heartbeatMd,
    requiredSkillIds,
    requiredSkillGroups: Array.from(groups, ([groupKey, skillIds]) => ({
      groupKey,
      skillIds,
    })),
  };
}

export type SnapshotSourceDetails = {
  label: string;
  explanation: string;
  templateKey: string;
  templateVersion: number;
};

export function isConfigurationSnapshot(
  snapshot: Snapshot,
): snapshot is ConfigurationSnapshot {
  return "pinType" in snapshot;
}

export function snapshotSourceDetails(
  snapshot: Snapshot,
): SnapshotSourceDetails {
  if (!isConfigurationSnapshot(snapshot)) {
    if (snapshot.organizationId === null) {
      return {
        label: "Built-in platform template",
        explanation: "Maintained by the platform and available to every organization.",
        templateKey: snapshot.templateKey,
        templateVersion: snapshot.version,
      };
    }

    if (snapshot.forkedFromPlatformTemplateId) {
      return {
        label: "Organization fork of a built-in template",
        explanation: "An organization-owned copy of a built-in platform template.",
        templateKey: snapshot.templateKey,
        templateVersion: snapshot.version,
      };
    }

    return {
      label: "Organization template",
      explanation: "Created and maintained by your organization.",
      templateKey: snapshot.templateKey,
      templateVersion: snapshot.version,
    };
  }

  const overrideSuffix =
    snapshot.pinType === "override"
      ? " This Agent-owned override is based on it."
      : " This is the shared template version selected for the Agent.";

  if (snapshot.sourceType === "platform") {
    return {
      label: "Built-in platform template",
      explanation: `Maintained by the platform.${overrideSuffix}`,
      templateKey: snapshot.sourceTemplateKey,
      templateVersion: snapshot.sourceTemplateVersion,
    };
  }

  if (snapshot.sourcePlatformTemplateId) {
    return {
      label: "Organization fork of a built-in template",
      explanation: `An organization-owned copy of a built-in platform template.${overrideSuffix}`,
      templateKey: snapshot.sourceTemplateKey,
      templateVersion: snapshot.sourceTemplateVersion,
    };
  }

  return {
    label: "Organization template",
    explanation: `Created and maintained by your organization.${overrideSuffix}`,
    templateKey: snapshot.sourceTemplateKey,
    templateVersion: snapshot.sourceTemplateVersion,
  };
}

export type TemplateSelectionType = "platform" | "organization" | "override";

export type TemplateSelectionOption = {
  value: string;
  selectionType: TemplateSelectionType;
  templateKey?: string;
  templateVersion?: number;
  overrideVersion?: number;
  snapshot: Snapshot;
  typeLabel:
    | "Built-in platform"
    | "Organization fork"
    | "Organization-owned"
    | "Agent override";
  name: string;
  version: number;
  updatedAt: string;
  isLatest: boolean;
  platformUpdateAvailable: boolean;
  sourceUpdateAvailable: boolean;
  searchText: string;
};

export function templateSelectionValue(
  selectionType: TemplateSelectionType,
  templateKey: string | undefined,
  version: number | undefined,
): string {
  return selectionType === "override"
    ? `override:${version ?? ""}`
    : `${selectionType}:${templateKey ?? ""}:${version ?? ""}`;
}
