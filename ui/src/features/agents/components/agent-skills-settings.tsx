"use client";

import { useRef, useState } from "react";
import Link from "next/link";

import { skillDetailHref } from "@/features/skills/scope";

import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import type { Agent } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";
import type { AgentConfigurationEditHandle } from "./agent-configuration-utils";
import { AgentSkillsTab } from "./agent-skills-tab";

export function AgentSkillsSettings({
  agent,
  canEdit,
  editing,
  onEdit,
}: {
  agent: Agent;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const panelRef = useRef<AgentConfigurationEditHandle>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [isValid, setIsValid] = useState(true);
  const { applyAndRestart } = useAgentApplyAndRestart(agent);

  async function applyChanges() {
    const action = panelRef.current;
    if (!action) return;
    await applyAndRestart(action.apply);
  }

  function cancelChanges() {
    panelRef.current?.cancel();
    setIsDirty(false);
    setIsValid(true);
    onEdit();
  }

  return (
    <AgentConfigurationSection
      title="Skills"
      description="Assigned tools are independent from the Markdown template. Required skills are protected by the active configuration."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || !isValid}
      restartOnApply={agent.status === "RUNNING"}
    >
      {editing && canEdit ? (
        <AgentSkillsTab
          ref={panelRef}
          agent={agent}
          isRunning={false}
          onDirtyChange={(dirty, valid = true) => {
            setIsDirty(dirty);
            setIsValid(valid);
          }}
        />
      ) : agent.skills.length > 0 ? (
        <div className="flex flex-col gap-2">
          {agent.skills.map((skill) => (
            <div key={skill.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
              <div>
                <Link
                  href={skillDetailHref({ kind: "agent", agentId: agent.id }, agent.organizationId, skill.id)}
                  className="font-medium text-[0.86rem] hover:underline"
                  style={{ color: "var(--ink-2)" }}
                >
                  {skill.name}
                </Link>
                <div className="text-[0.76rem]" style={{ color: "var(--ink-4)" }}>{skill.source}{skill.required ? " · Required by active template" : ""}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[0.72rem]" style={{ color: "var(--ink-4)" }}>v{skill.version}</span>
                <span className="font-mono text-[0.72rem]" style={{ color: "var(--ink-4)" }}>{skill.requiredProviders.length > 0 ? skill.requiredProviders.join(", ") : "No provider"}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-4)" }}>No skills are assigned to this Agent.</p>
      )}
    </AgentConfigurationSection>
  );
}
