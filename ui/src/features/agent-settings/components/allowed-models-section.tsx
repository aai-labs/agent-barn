"use client";

import { useMemo, useState } from "react";
import { Loader2, Search, X } from "lucide-react";

import { SettingsErrorText } from "@/components/settings/settings-error-text";
import { SettingsSectionHeading } from "@/components/settings/settings-section-heading";
import { SettingsSection } from "@/components/settings/settings-section";
import { useModels } from "@/features/agents/hooks/use-models";
import { useOrganization } from "@/features/organizations/hooks/use-organization";
import { useUpdateOrganization } from "@/features/organizations/hooks/use-organization-actions";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";

import {
  getEffectiveModels,
  getOrphanedModels,
  stripPrefix,
} from "../allowed-models-utils";
import { useAgentSettings } from "../hooks/use-agent-settings";

export function AllowedModelsSection({
  canEdit,
  editing,
  onEdit,
}: {
  canEdit: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const { selectedOrganization } = useOrganizationContext();
  const organizationId = selectedOrganization?.id ?? "";
  const { organization } = useOrganization(organizationId);
  // The full catalog, not the allowlisted subset — this control is what edits it.
  const { models, isLoading } = useModels({ catalog: true });
  const { settings } = useAgentSettings();
  // The guard's refusal names the Agents in the way; that belongs beside the list.
  const updateOrg = useUpdateOrganization({ toastOnError: false });

  // Only an Organization-owned default is constrained by the allowlist. A platform
  // default can change during deploys, so organizations that follow it must remain
  // free to omit it from their own allowlist.
  const requiredModel =
    settings?.defaultModelSource === "organization"
      ? settings.effectiveDefaultModel
      : "";

  // Drafts are null until touched, so the control follows the server without an
  // effect syncing two sources of truth — and without a frame of empty state.
  const [selectedDraft, setSelectedDraft] = useState<string[] | null>(null);
  const [orphanDraft, setOrphanDraft] = useState<string[] | null>(null);
  const [search, setSearch] = useState("");

  const baseline = useMemo(
    () => getEffectiveModels(organization?.allowedModels, models, requiredModel),
    [organization?.allowedModels, models, requiredModel],
  );
  const baselineOrphans = useMemo(
    () => getOrphanedModels(organization?.allowedModels, models),
    [organization?.allowedModels, models],
  );

  const selected = selectedDraft ?? baseline;
  const orphaned = orphanDraft ?? baselineOrphans;

  const filtered = useMemo(() => {
    if (!search) return models;
    const query = search.toLowerCase();
    return models.filter(
      (model) =>
        model.label.toLowerCase().includes(query) || model.value.toLowerCase().includes(query),
    );
  }, [models, search]);

  const isDirty =
    JSON.stringify([...selected].sort()) !== JSON.stringify([...baseline].sort()) ||
    JSON.stringify([...orphaned].sort()) !== JSON.stringify([...baselineOrphans].sort());

  function toggle(value: string) {
    if (value === requiredModel) return;
    setSelectedDraft((prev) => {
      const current = prev ?? baseline;
      return current.includes(value)
        ? current.filter((model) => model !== value)
        : [...current, value];
    });
  }

  async function applyChanges() {
    const cleaned = [
      ...new Set([...selected.map((model) => stripPrefix(model)), ...orphaned]),
    ];
    await updateOrg.mutateAsync({ organizationId, data: { allowedModels: cleaned } });
    setSelectedDraft(null);
    setOrphanDraft(null);
  }

  function cancelChanges() {
    setSelectedDraft(null);
    setOrphanDraft(null);
    setSearch("");
    updateOrg.reset();
    onEdit();
  }

  return (
    <SettingsSection
      title="Allowed models"
      description="The models Agents in this organization may be pointed at."
      canEdit={canEdit}
      editing={editing}
      onEdit={onEdit}
      onApply={applyChanges}
      onCancel={cancelChanges}
      onApplied={onEdit}
      applyDisabled={!isDirty || updateOrg.isPending}
      errorsShownInline
      applyLabel="Save models"
      applyPendingLabel="Saving…"
      confirm={{
        title: "Save the allowed model list?",
        description:
          "Removing a model no Agent is pinned to takes effect immediately. If an Agent still names one, the save is refused and tells you which.",
      }}
    >
      {isLoading ? (
        <div className="flex items-center gap-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          <Loader2 size={15} className="animate-spin" /> Loading model catalog…
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <SettingsSectionHeading
            title="Allowed models"
            description="The models Agents in this organization may be pointed at."
          />
          {(selected.length > 0 || orphaned.length > 0) && (
            <div className="flex flex-wrap gap-2">
              {selected.map((value) => {
                const model = models.find((entry) => entry.value === value);
                const required = value === requiredModel;
                return (
                  <span
                    key={value}
                    className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[0.78rem]"
                    style={{
                      background: "var(--bg-soft)",
                      border: "1px solid var(--line)",
                      color: "var(--ink-2)",
                    }}
                  >
                    {model ? model.label : stripPrefix(value)}
                    {required ? (
                      <span className="text-[0.7rem]" style={{ color: "var(--ink-4)" }}>
                        default
                      </span>
                    ) : (
                      editing &&
                      canEdit && (
                        <button
                          type="button"
                          aria-label={`Remove ${model ? model.label : stripPrefix(value)}`}
                          onClick={() => toggle(value)}
                          style={{ color: "var(--ink-4)" }}
                        >
                          <X size={14} />
                        </button>
                      )
                    )}
                  </span>
                );
              })}
              {orphaned.map((value) => (
                <span
                  key={`orphan-${value}`}
                  title="Previously allowed but no longer in the OpenRouter catalog. It stays in the list unless removed."
                  className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[0.78rem]"
                  style={{
                    background: "var(--warn-soft)",
                    border: "1px solid var(--warn)",
                    color: "var(--warn)",
                  }}
                >
                  {value}
                  <span className="text-[0.7rem]">not in catalog</span>
                  {editing && canEdit && (
                    <button
                      type="button"
                      aria-label={`Remove ${value}`}
                      onClick={() => setOrphanDraft((prev) => (prev ?? baselineOrphans).filter((model) => model !== value))}
                      style={{ color: "var(--warn)" }}
                    >
                      <X size={14} />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}

          {editing && canEdit ? (
            <>
              <div className="relative max-w-md">
                <Search
                  size={15}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
                  style={{ color: "var(--ink-4)" }}
                  aria-hidden
                />
                <input
                  type="text"
                  className="af-input pl-9"
                  placeholder="Search models…"
                  aria-label="Search models"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              <div
                className="flex max-h-[19rem] flex-col gap-1 overflow-y-auto rounded-xl p-1"
                style={{ border: "1px solid var(--line)" }}
              >
                {filtered.map((model) => {
                  const required = model.value === requiredModel;
                  return (
                    <label
                      key={model.value}
                      className="af-hover-bg flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2"
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded disabled:opacity-50"
                        style={{ accentColor: "var(--ink)", borderColor: "var(--line-strong)" }}
                        checked={selected.includes(model.value)}
                        disabled={required}
                        onChange={() => toggle(model.value)}
                      />
                      <span className="flex min-w-0 flex-col">
                        <span
                          className="truncate text-[0.84rem] font-medium"
                          style={{ color: "var(--ink)" }}
                        >
                          {model.label}
                          {required && (
                            <span
                              className="ml-2 text-[0.7rem] font-normal"
                              style={{ color: "var(--ink-4)" }}
                            >
                              default — required
                            </span>
                          )}
                        </span>
                        <span
                          className="truncate font-mono text-[0.72rem]"
                          style={{ color: "var(--ink-4)" }}
                        >
                          {model.value}
                        </span>
                      </span>
                    </label>
                  );
                })}
                {filtered.length === 0 && (
                  <div className="px-2.5 py-2 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
                    No models match.
                  </div>
                )}
              </div>
              <p className="m-0 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
                The default model must stay in this list. To remove it, change the default
                first — and point any Agent pinned to a model at something else before
                removing that one.
              </p>
              {updateOrg.error && (
                <SettingsErrorText>
                  {updateOrg.error instanceof Error ? updateOrg.error.message : "Save failed"}
                </SettingsErrorText>
              )}
            </>
          ) : (
            selected.length === 0 &&
            orphaned.length === 0 && (
              <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
                No models are allowed yet, so Agents cannot be created.
              </p>
            )
          )}
        </div>
      )}
    </SettingsSection>
  );
}
