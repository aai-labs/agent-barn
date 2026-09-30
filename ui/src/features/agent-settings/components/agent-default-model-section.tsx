"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSection } from "@/components/settings/settings-section";
import { ModelSelect } from "@/features/agents/components/model-select";
import { formatModelName } from "@/features/agents/utils";

import { useAgentSettings } from "../hooks/use-agent-settings";
import { useUpdateAgentSettings } from "../hooks/use-update-agent-settings";

function plural(count: number, singular: string, plural_: string) {
  return `${count} ${count === 1 ? singular : plural_}`;
}

/**
 * Names what changing the default will actually do, using the server's counts rather
 * than anything the client tallies up. Agents are not restarted, so the change lands
 * on each one's next start — saying so here is the whole point of the dialog.
 */
function blastRadius(inheriting: number, override: number, model: string) {
  const followers =
    inheriting === 0
      ? "No Agents currently follow the default"
      : `${plural(inheriting, "Agent follows", "Agents follow")} the default and will use ${formatModelName(model)} after their next restart`;
  const pinned =
    override === 0
      ? ""
      : ` ${plural(override, "Agent has", "Agents have")} their own model and are unaffected.`;
  return `${followers}.${pinned}`;
}

export function AgentDefaultModelSection({
  canEdit,
  editing,
  onEdit,
}: {
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const { settings, isLoading } = useAgentSettings();
  // A rejected default is explained beside the picker, not in a banner.
  const updateSettings = useUpdateAgentSettings({ toastOnError: false });
  // null means "untouched", so the control follows the server value until the user
  // actually picks something. Deriving beats syncing two sources of truth in an effect.
  const [draft, setDraft] = useState<string | null>(null);

  const effectiveDefault = settings?.effectiveDefaultModel ?? "";
  const stored = settings?.defaultModel ?? "";
  // An organization that has never chosen a default starts from the platform value
  // rather than an empty picker.
  const selected = draft ?? (stored || effectiveDefault);
  const isDirty = Boolean(selected) && selected !== stored;

  async function applyChanges() {
    await updateSettings.mutateAsync({ defaultModel: selected });
    setDraft(null);
  }

  function cancelChanges() {
    setDraft(null);
    updateSettings.reset();
    onEdit();
  }

  return (
    <SettingsSection
      title="Default model"
      description="The runtime model Agents use unless they have been given one of their own."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || updateSettings.isPending}
      errorsShownInline
      applyLabel="Change default"
      applyPendingLabel="Changing…"
      confirm={{
        title: "Change the default model?",
        description: settings
          ? blastRadius(settings.inheritingAgentCount, settings.overrideAgentCount, selected)
          : "",
      }}
    >
      {isLoading ? (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading Agent defaults…
        </div>
      ) : editing && canEdit ? (
        <div className="flex max-w-xl flex-col gap-4">
          <label
            className="flex flex-col gap-1.5 text-[0.84rem] font-medium"
            style={{ color: "var(--ink)" }}
          >
            Default model
            <ModelSelect value={selected} onChange={setDraft} aria-label="Default model" />
          </label>
          <p className="m-0 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            Only models in the Allowed Models list below can be made the default. Agents already
            running keep their current model until they are restarted.
          </p>
          {updateSettings.error && (
            <SettingsErrorText>
              {updateSettings.error instanceof Error ? updateSettings.error.message : "Save failed"}
            </SettingsErrorText>
          )}
        </div>
      ) : (
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          <div>
            <dt
              className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Default model
            </dt>
            <dd className="mb-0 mt-1 font-mono text-[0.84rem]" style={{ color: "var(--ink-2)" }}>
              {formatModelName(effectiveDefault) || "—"}
            </dd>
          </div>
          <div>
            <dt
              className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Set by
            </dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
              {settings?.defaultModelSource === "organization"
                ? "This organization"
                : "Platform default"}
            </dd>
          </div>
          <div>
            <dt
              className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Following the default
            </dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
              {settings ? plural(settings.inheritingAgentCount, "Agent", "Agents") : "—"}
            </dd>
          </div>
          <div>
            <dt
              className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Using their own model
            </dt>
            <dd className="mb-0 mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
              {settings ? plural(settings.overrideAgentCount, "Agent", "Agents") : "—"}
            </dd>
          </div>
        </dl>
      )}
    </SettingsSection>
  );
}
