"use client";

import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { SettingsSection } from "@/components/settings/settings-section";
import type { Agent } from "@/features/agents/schemas";
import { useAgentApplyAndRestart } from "@/features/agents/hooks/use-agent-apply-and-restart";

import { useSetAgentMemory } from "../hooks/use-set-agent-memory";

function StateBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[0.72rem] font-medium"
      style={{
        background: enabled ? "var(--ok-soft)" : "var(--bg-soft)",
        border: `1px solid ${enabled ? "color-mix(in srgb, var(--ok) 35%, var(--line))" : "var(--line)"}`,
        color: enabled ? "var(--ok)" : "var(--ink-3)",
      }}
    >
      {enabled ? "On" : "Off"}
    </span>
  );
}

export function AgentMemorySettings({
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
  const setMemory = useSetAgentMemory(agent.id);
  const { applyAndRestart, isPending: isRestartPending } = useAgentApplyAndRestart(agent);
  const restartOnSave = agent.status === "RUNNING" && agent.allowedActions.includes("agent.lifecycle.manage");
  const [applyError, setApplyError] = useState<unknown>(null);
  const [draft, setDraft] = useState(agent.memoryEnabled);
  const isDirty = draft !== agent.memoryEnabled;
  const error = applyError || setMemory.error;

  async function applyChanges() {
    setApplyError(null);
    try {
      if (restartOnSave) {
        await applyAndRestart(() => setMemory.mutateAsync(draft).then(() => undefined));
      } else {
        await setMemory.mutateAsync(draft);
      }
    } catch (error) {
      setApplyError(error);
      throw error;
    }
  }

  function cancelChanges() {
    setDraft(agent.memoryEnabled);
    setMemory.reset();
    setApplyError(null);
    onEdit();
  }

  return (
    <SettingsSection
      title="Long-term memory"
      description="Let this Agent remember durable facts across conversations."
      canEdit={canEdit}
      editing={editing}
      onEdit={() => {
        setDraft(agent.memoryEnabled);
        setApplyError(null);
        onEdit();
      }}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || setMemory.isPending || isRestartPending}
      applyLabel={restartOnSave ? "Save and Restart" : "Save"}
      applyPendingLabel={restartOnSave ? "Saving and Restarting…" : "Saving…"}
      errorsShownInline
      confirm={
        restartOnSave
          ? {
              title: "Save memory settings and restart the Agent?",
              description: `${agent.name} will stop, save its memory setting, and start again with memory ${draft ? "on" : "off"}. Memories already saved are kept. People with access to this Agent share what it remembers.`,
            }
          : draft
          ? {
              title: "Turn on long-term memory?",
              description: `${agent.name} will start remembering durable facts from its conversations. If it is already running, restart it so memory takes effect. People with access to ${agent.name} share what it remembers.`,
            }
          : {
              title: "Turn off long-term memory?",
              description: `${agent.name} stops recalling and saving memories immediately. Memories already saved are kept and can still be viewed, and Agents granted access to them can still recall them.`,
            }
      }
    >
      <div className="flex max-w-2xl flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
          <span className="font-medium" style={{ color: "var(--ink)" }}>
            Long-term memory
          </span>
          <StateBadge enabled={agent.memoryEnabled} />
        </div>

        {editing && canEdit ? (
          <Label className="flex items-start gap-2 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            <Checkbox
              className="mt-0.5"
              checked={draft}
              onCheckedChange={(checked) => setDraft(checked === true)}
            />
            <span>Remember durable facts across conversations</span>
          </Label>
        ) : null}

        {Boolean(error) && (
          <span role="alert" className="text-xs" style={{ color: "var(--err)" }}>
            {error instanceof Error ? error.message : "Saving memory settings failed."}
          </span>
        )}

        <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          <li>
            Memory adds to the memory this Agent&apos;s runtime already has; it never replaces it.
          </li>
          <li>
            Turning it on applies the next time the Agent starts. Save and Restart applies changes to a running Agent.
          </li>
          {agent.status === "RUNNING" && !agent.allowedActions.includes("agent.lifecycle.manage") && (
            <li>You can save this setting; someone with lifecycle access must restart the Agent to activate it.</li>
          )}
          <li>Turning it off takes effect immediately. Memories already saved are kept.</li>
          <li>
            Memories are shared by everyone who uses this Agent: something one person tells it can be recalled
            in another person&apos;s conversation.
          </li>
          {!canEdit && <li>Only people who can manage this Agent&apos;s memory can change this setting.</li>}
        </ul>
      </div>
    </SettingsSection>
  );
}
