"use client";

import { useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { currentModelOf, formatModelName } from "../utils";
import { useAgentApplyAndRestart } from "../hooks/use-agent-apply-and-restart";
import { useModels } from "../hooks/use-models";
import { useUpdateAgent } from "../hooks/use-update-agent";
import type { Agent, CommandApprovalMode } from "../schemas";
import { ModelChoice } from "./model-choice";
import { ModelSourceBadge } from "./model-source-badge";
import { PendingModelNote } from "./pending-model-note";
import { AgentConfigurationSection } from "./agent-configuration-section";

export function AgentProfileSettings({
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
  const updateAgent = useUpdateAgent();
  // The organization's default, not agent.effectiveModel — for an Agent that already
  // has its own model those differ, and this control is about what it would inherit.
  const { defaultModel: organizationDefaultModel } = useModels();
  const [name, setName] = useState(agent.name);
  const [model, setModel] = useState<string | null>(agent.model || null);
  const [approvalMode, setApprovalMode] = useState<CommandApprovalMode>(agent.approvalMode);
  const { applyAndRestart } = useAgentApplyAndRestart(agent);
  const approvalLabel = agent.agentType === "hermes" ? agent.approvalMode : "Managed by OpenClaw";
  const isDirty =
    name.trim() !== agent.name ||
    (model ?? "") !== agent.model ||
    (agent.agentType === "hermes" && approvalMode !== agent.approvalMode);

  async function applyChanges() {
    await applyAndRestart(() =>
      updateAgent.mutateAsync({
        agentId: agent.id,
        name: name.trim(),
        model,
        ...(agent.agentType === "hermes" ? { approvalMode } : {}),
      }).then(() => undefined),
    );
  }

  function cancelChanges() {
    setName(agent.name);
    setModel(agent.model || null);
    setApprovalMode(agent.approvalMode);
    updateAgent.reset();
    onEdit();
  }

  return (
    <AgentConfigurationSection
      title="Profile"
      description="Identity, runtime preferences, and deployment facts for this Agent."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || updateAgent.isPending}
      restartOnApply={agent.status === "RUNNING"}
    >
      {editing && canEdit ? (
        <div className="flex max-w-xl flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
            Agent name
            <input className="af-input" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <fieldset className="flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
              Model
            </legend>
            <ModelChoice
              value={model}
              effectiveDefaultModel={organizationDefaultModel}
              onChange={setModel}
            />
          </fieldset>
          {agent.agentType === "hermes" && (
            <label className="flex flex-col gap-1.5 text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>
              Command approval
              <Select value={approvalMode} onValueChange={(value) => setApprovalMode(value as CommandApprovalMode)}>
                <SelectTrigger aria-label="Command approval">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto — approve low-risk commands automatically</SelectItem>
                  <SelectItem value="manual">Manual — always ask before running commands</SelectItem>
                  <SelectItem value="off">Off — skip all approval prompts</SelectItem>
                </SelectContent>
              </Select>
            </label>
          )}
          {updateAgent.error && (
            <span className="text-xs" style={{ color: "var(--err)" }}>
              {updateAgent.error instanceof Error ? updateAgent.error.message : "Save failed"}
            </span>
          )}
        </div>
      ) : (
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <div>
            <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Agent name</dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{agent.name}</dd>
          </div>
          <div>
            <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Model</dt>
            <dd className="mb-0 mt-1 flex flex-wrap items-center gap-2 font-mono text-[0.84rem]" style={{ color: "var(--ink-2)" }}>
              {formatModelName(currentModelOf(agent)) || "—"}
              <ModelSourceBadge source={agent.modelSource} />
            </dd>
            <PendingModelNote pendingModel={agent.pendingModel} />
          </div>
          <div>
            <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Runtime</dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{agent.agentType === "hermes" ? "Hermes" : "OpenClaw"}</dd>
          </div>
          <div>
            <dt className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Command approval</dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{approvalLabel}</dd>
          </div>
        </dl>
      )}

      <Separator className="my-6" />

      <div>
        <h3 className="m-0 text-[0.92rem] font-semibold" style={{ color: "var(--ink-2)" }}>
          Runtime & deployment
        </h3>
        <p className="mb-4 mt-1 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
          These operational facts are managed by the platform and reconciled whenever the Agent starts or stops.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Lifecycle</div>
            <div className="mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{agent.status}</div>
          </div>
          <div className="rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Runtime</div>
            <div className="mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>{agent.agentType === "hermes" ? "Hermes" : "OpenClaw"}</div>
          </div>
          <div className="rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Communications</div>
            <div className="mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>Managed as independent connections</div>
          </div>
          <div className="rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
            <div className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>Resource management</div>
            <div className="mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>Managed on start / stop</div>
          </div>
        </div>
        <p className="mb-0 mt-4 text-[0.8rem]" style={{ color: "var(--ink-4)" }}>
          Live deployment inventory is intentionally not editable from this page. Starting the Agent reconciles its deployment, service, storage, secrets, and configuration resources.
        </p>
      </div>
    </AgentConfigurationSection>
  );
}
