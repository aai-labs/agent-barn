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

const providerIcons: Record<string, string> = {
  openai: "openai",
  anthropic: "anthropic",
  google: "googlegemini",
  "meta-llama": "meta",
  mistralai: "mistralai",
  deepseek: "deepseek",
};

function modelDetails(model: { value: string; contextLength?: number | null; pricing?: unknown }) {
  const provider = stripPrefix(model.value).split("/")[0];
  const pricing = model.pricing && typeof model.pricing === "object" ? model.pricing as Record<string, unknown> : {};
  const price = (value: unknown) => {
    if (typeof value !== "string" && typeof value !== "number") return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? `$${(number * 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 4 })}` : null;
  };
  const input = price(pricing.prompt);
  const output = price(pricing.completion);
  return { provider, context: model.contextLength ? `${model.contextLength.toLocaleString()} tokens` : null, input, output };
}

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
              <div className="grid max-h-[36rem] grid-cols-1 gap-3 overflow-y-auto sm:grid-cols-2">
                {filtered.map((model) => {
                  const required = model.value === requiredModel;
                  const details = modelDetails(model);
                  const checked = selected.includes(model.value);
                  return (
                    <label
                      key={model.value}
                      className="af-hover-bg flex cursor-pointer flex-col gap-3 rounded-xl p-4"
                      style={{ border: `1px solid ${checked ? "var(--line-strong)" : "var(--line)"}`, background: checked ? "var(--bg-soft)" : undefined }}
                    >
                      <span className="flex items-start gap-3">
                        <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-xs font-bold uppercase" style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}>
                          {providerIcons[details.provider] ? (
                            // Provider logos are decorative; the provider name is alongside them.
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={`/brand/models/${providerIcons[details.provider]}.svg`} alt="" className="h-5 w-5 dark:invert" />
                          ) : details.provider.slice(0, 2)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>{model.label}</span>
                          <span className="block text-[0.75rem]" style={{ color: "var(--ink-3)" }}>{details.provider}</span>
                        </span>
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded disabled:opacity-50"
                          style={{ accentColor: "var(--ink)", borderColor: "var(--line-strong)" }}
                          checked={checked}
                          disabled={required}
                          onChange={() => toggle(model.value)}
                          aria-label={`${model.label}${required ? " (default, required)" : ""}`}
                        />
                      </span>
                      <span className="flex flex-wrap gap-2 text-[0.72rem]" style={{ color: "var(--ink-3)" }}>
                        {required && <span>Default · required</span>}
                        {details.context && <span>{details.context} context</span>}
                      </span>
                      <span className="flex flex-wrap justify-between gap-2 border-t pt-3 text-[0.72rem]" style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}>
                        <span>Input {details.input ?? "—"} / 1M tokens</span>
                        <span>Output {details.output ?? "—"} / 1M tokens</span>
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
