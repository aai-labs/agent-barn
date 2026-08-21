import {
  FileCode2,
  KeyRound,
  MessageSquare,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from "lucide-react";

import { SettingsSidebar } from "@/components/settings/settings-sidebar";

import type { Agent } from "../schemas";
import {
  AGENT_CONFIGURATION_SECTIONS,
  configurationSectionLabel,
  type AgentConfigurationSectionKey,
} from "./agent-configuration-utils";

const ICONS = {
  template: FileCode2,
  profile: UserRound,
  channels: MessageSquare,
  skills: Sparkles,
  keys: KeyRound,
  override: SlidersHorizontal,
  danger: ShieldAlert,
} as const;

export function AgentConfigurationSidebar({
  agent,
  activeSection,
  onSectionChange,
}: {
  agent: Pick<Agent, "platform">;
  activeSection: AgentConfigurationSectionKey;
  onSectionChange: (section: AgentConfigurationSectionKey) => void;
}) {
  const items = AGENT_CONFIGURATION_SECTIONS.map((section) => {
    const Icon = ICONS[section.key];
    return {
      key: section.key,
      // Relabelled per platform: a Telegram Agent has chats, a Teams Agent an endpoint.
      label: configurationSectionLabel(section.key, agent),
      icon: <Icon size={15} aria-hidden />,
    };
  });

  return (
    <SettingsSidebar
      eyebrow="Agent settings"
      items={items}
      activeKey={activeSection}
      onSelect={(key) => onSectionChange(key as AgentConfigurationSectionKey)}
    />
  );
}
