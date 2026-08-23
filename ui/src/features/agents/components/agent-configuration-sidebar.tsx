import {
  FileCode2,
  KeyRound,
  MessageSquare,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from "lucide-react";

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
  return (
    <aside className="w-full flex-shrink-0 lg:sticky lg:top-[77px] lg:w-56">
      <div className="mb-3 px-3 text-[0.7rem] font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--ink-4)" }}>
        Agent settings
      </div>
      <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {AGENT_CONFIGURATION_SECTIONS.map((section) => {
          const Icon = ICONS[section.key];
          const isActive = activeSection === section.key;
          return (
            <button
              key={section.key}
              type="button"
              className="flex min-w-max items-center gap-2 rounded-lg px-3 py-2 text-left text-[0.82rem] font-medium transition-colors lg:w-full"
              style={{
                background: isActive ? "var(--bg-soft)" : "transparent",
                color: isActive ? "var(--ink)" : "var(--ink-3)",
                fontWeight: isActive ? 600 : 500,
              }}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSectionChange(section.key)}
            >
              <Icon size={15} aria-hidden />
              <span>{configurationSectionLabel(section.key, agent)}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
