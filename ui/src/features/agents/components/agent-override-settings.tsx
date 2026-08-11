"use client";

import { useState } from "react";
import { FileText, Loader2, Pencil, Send } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { toastError } from "@/shared/toast";
import {
  usePublishAgentOverride,
  useStartAgentOverrideDraft,
  useUpdateAgentOverrideDraft,
} from "../hooks/use-agent-override-actions";
import type { AgentConfiguration, AgentOverrideDraft } from "../schemas";
import { AgentConfigurationSection } from "./agent-configuration-section";
import { AgentConfigurationOverrideHistory } from "./configuration-override-history";
import { ConfigurationReadOnlySnapshot } from "./configuration-read-only-snapshot";
import { AgentOverrideDraftEditor } from "./configuration-draft-editor";
import {
  draftToForm,
  type DraftForm,
  type DraftTextField,
  type RequiredSkillGroupDraft,
} from "./agent-configuration-utils";

export function AgentOverrideSettings({
  agentId,
  configuration,
  canEdit,
  editing,
  onEdit,
  onPublished,
}: {
  agentId: string;
  configuration: AgentConfiguration;
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
  onPublished: () => void;
}) {
  const startDraftMutation = useStartAgentOverrideDraft();
  const updateDraft = useUpdateAgentOverrideDraft();
  const publishDraft = usePublishAgentOverride();
  const [draftOverride, setDraftOverride] = useState<AgentOverrideDraft | null>(null);
  const [formOverride, setFormOverride] = useState<DraftForm | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const activeDraft = draftOverride ?? configuration.draft;
  const form = formOverride ?? (activeDraft ? draftToForm(activeDraft) : null);
  const activeOverride = configuration.active.pinType === "override";
  const isEditingDraft = editing && canEdit;

  function createDraft() {
    startDraftMutation.mutate(agentId, {
      onSuccess: (draft) => {
        setDraftOverride(draft);
        setFormOverride(draftToForm(draft));
        if (!editing) onEdit();
      },
      onError: (error) => toastError(error),
    });
  }

  function handleChange(field: DraftTextField, value: string) {
    setFormOverride((current) => (current ? { ...current, [field]: value } : current));
  }

  function handleRequirementsChange(requiredSkillIds: string[], requiredSkillGroups: RequiredSkillGroupDraft[]) {
    setFormOverride((current) => (current ? { ...current, requiredSkillIds, requiredSkillGroups } : current));
  }

  function saveDraft() {
    if (!activeDraft || !form) return;
    const { templateName, description, requiredSkillIds, requiredSkillGroups, ...artifacts } = form;
    updateDraft.mutate(
      {
        agentId,
        expectedUpdatedAt: activeDraft.updatedAt,
        templateName: templateName.trim(),
        description: description.trim() || null,
        requiredSkillIds,
        requiredSkillGroups,
        ...artifacts,
      },
      {
        onSuccess: (draft) => {
          setDraftOverride(draft);
          setFormOverride(null);
          onEdit();
        },
        onError: (error) => toastError(error),
      },
    );
  }

  function cancelEditing() {
    setFormOverride(null);
    updateDraft.reset();
    onEdit();
  }

  async function publish() {
    if (!activeDraft) return;
    try {
      await publishDraft.mutateAsync({ agentId, expectedUpdatedAt: activeDraft.updatedAt });
      setPublishOpen(false);
      setDraftOverride(null);
      setFormOverride(null);
      onPublished();
    } catch (error) {
      toastError(error);
    }
  }

  return (
    <>
      <AgentConfigurationSection
        title="Agent-owned override"
        description="An override is private to this Agent. Drafts can be saved without changing the active pin; publishing creates an immutable version."
      >
        <div className="flex flex-col gap-5">
          {!activeDraft && (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl p-5" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
              <div>
                <div className="flex items-center gap-2">
                  <FileText size={16} style={{ color: "var(--ink-3)" }} />
                  <h3 className="m-0 text-[0.98rem] font-semibold" style={{ color: "var(--ink-2)" }}>
                    {activeOverride ? "No override draft" : "No active override"}
                  </h3>
                </div>
                <p className="mb-0 mt-1 max-w-xl text-[0.82rem]" style={{ color: "var(--ink-3)" }}>
                  {activeOverride
                    ? "Create a new private draft from the active override when you need another Agent-specific revision."
                    : "This Agent currently uses its shared template. Create a private draft when you need Agent-specific instructions."}
                </p>
              </div>
              {canEdit && (
                <button type="button" className="af-btn af-btn-primary" disabled={startDraftMutation.isPending} onClick={createDraft}>
                  {startDraftMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                  {startDraftMutation.isPending ? "Creating…" : activeOverride ? "Create new draft" : "Create override"}
                </button>
              )}
            </div>
          )}

          {activeOverride && <ConfigurationReadOnlySnapshot snapshot={configuration.active} title="Active override" />}

          {activeDraft && form && (
            isEditingDraft ? (
              <AgentOverrideDraftEditor
                draft={activeDraft}
                form={form}
                onChange={handleChange}
                onRequirementsChange={handleRequirementsChange}
                onSave={saveDraft}
                onCancel={cancelEditing}
                isSaving={updateDraft.isPending}
              />
            ) : (
              <ConfigurationReadOnlySnapshot
                snapshot={activeDraft}
                title="Override draft"
                actions={
                  canEdit && (
                    <>
                      <button type="button" className="af-btn" onClick={onEdit}>
                        <Pencil size={14} /> Edit
                      </button>
                      <button
                        type="button"
                        className="af-btn af-btn-primary"
                        disabled={publishDraft.isPending}
                        onClick={() => setPublishOpen(true)}
                      >
                        <Send size={14} /> Publish
                      </button>
                    </>
                  )
                }
              />
            )
          )}

          {configuration.overrideVersions.length > 0 && (
            <AgentConfigurationOverrideHistory versions={configuration.overrideVersions} />
          )}
        </div>
      </AgentConfigurationSection>
      <ConfirmationDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        title="Publish this override?"
        description="Publishing freezes this draft as an immutable Agent-owned version. The active configuration will stay unchanged until you apply it from Template selection."
        confirmLabel="Publish override"
        pendingLabel="Publishing…"
        onConfirm={() => void publish()}
        isPending={publishDraft.isPending}
      />
    </>
  );
}
