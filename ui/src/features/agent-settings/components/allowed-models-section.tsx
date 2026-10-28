"use client";

import { useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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

function ProviderIcon({ provider }: { provider: string }) {
  return <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-xs font-bold uppercase" style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}>
    {providerIcons[provider] ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={`/brand/models/${providerIcons[provider]}.svg`} alt="" className="h-5 w-5 dark:invert" />
    ) : provider.slice(0, 2)}
  </span>;
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
  const { models, isLoading, error: catalogError } = useModels({ catalog: true });
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
  const [catalogSearch, setCatalogSearch] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toAdd, setToAdd] = useState<string[]>([]);

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

  const query = search.toLowerCase();
  const visibleSelected = selected.filter((value) => {
    const model = models.find((entry) => entry.value === value);
    return !query || value.toLowerCase().includes(query) || model?.label.toLowerCase().includes(query);
  });
  const visibleOrphans = orphaned.filter((value) => value.toLowerCase().includes(query));
  const catalogQuery = catalogSearch.toLowerCase();
  const filteredCatalog = models.filter((model) =>
    model.label.toLowerCase().includes(catalogQuery) || model.value.toLowerCase().includes(catalogQuery),
  );

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
    setDialogOpen(false);
    setToAdd([]);
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
      applyDisabled={!isDirty || updateOrg.isPending || !!catalogError}
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
          {catalogError ? (
            <SettingsErrorText>Could not load the model catalog. Reload the page to try again.</SettingsErrorText>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>{selected.length + orphaned.length} enabled</span>
                {editing && canEdit && (
                  <button type="button" className="af-btn af-btn-primary" onClick={() => { setToAdd([]); setCatalogSearch(""); setDialogOpen(true); }}>
                    Add models
                  </button>
                )}
              </div>
              <div className="relative max-w-md">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--ink-4)" }} aria-hidden />
                <input className="af-input pl-9" placeholder="Search enabled models…" aria-label="Search enabled models" value={search} onChange={(event) => setSearch(event.target.value)} />
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {visibleSelected.map((value) => {
                  const model = models.find((entry) => entry.value === value);
                  const details = modelDetails(model ?? { value });
                  const required = value === requiredModel;
                  return (
                    <div key={value} className="flex flex-col gap-3 rounded-xl p-4" style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}>
                      <div className="flex items-start gap-3">
                        <ProviderIcon provider={details.provider} />
                        <div className="min-w-0 flex-1">
                          <div className="text-[0.84rem] font-medium" style={{ color: "var(--ink)" }}>{model?.label ?? stripPrefix(value)}</div>
                          <div className="text-[0.75rem]" style={{ color: "var(--ink-3)" }}>{details.provider}</div>
                        </div>
                        {required ? <span className="text-[0.72rem]">Default · required</span> : editing && canEdit && <button type="button" className="text-[0.75rem]" onClick={() => toggle(value)} aria-label={`Remove ${model?.label ?? stripPrefix(value)}`}>Remove</button>}
                      </div>
                      {details.context && <div className="text-[0.72rem]" style={{ color: "var(--ink-3)" }}>{details.context} context</div>}
                      <div className="flex flex-wrap justify-between gap-2 border-t pt-3 text-[0.72rem]" style={{ borderColor: "var(--line)", color: "var(--ink-3)" }}>
                        <span>Input {details.input ?? "—"} / 1M tokens</span><span>Output {details.output ?? "—"} / 1M tokens</span>
                      </div>
                    </div>
                  );
                })}
                {visibleOrphans.map((value) => (
                  <div key={value} className="flex items-center justify-between gap-3 rounded-xl p-4 text-[0.8rem]" style={{ border: "1px solid var(--warn)", color: "var(--warn)" }}>
                    <span>{value} · not in catalog</span>
                    {editing && canEdit && <button type="button" aria-label={`Remove ${value}`} onClick={() => setOrphanDraft((prev) => (prev ?? baselineOrphans).filter((model) => model !== value))}>Remove</button>}
                  </div>
                ))}
              </div>
              {visibleSelected.length + visibleOrphans.length === 0 && <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>{search ? "No enabled models match." : "No models are allowed yet, so Agents cannot be created."}</p>}
              {editing && canEdit && <p className="m-0 text-[0.8rem]" style={{ color: "var(--ink-3)" }}>An organization-owned default must stay in this list. Point any Agent pinned to a model at something else before removing it.</p>}
              {updateOrg.error && <SettingsErrorText>{updateOrg.error instanceof Error ? updateOrg.error.message : "Save failed"}</SettingsErrorText>}
              <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent className="max-h-[85vh] sm:max-w-2xl">
                  <DialogHeader><DialogTitle>Add models</DialogTitle><DialogDescription>Search the OpenRouter catalog and select models to allow.</DialogDescription></DialogHeader>
                  <input className="af-input" placeholder="Search by model or provider…" aria-label="Search catalog" value={catalogSearch} onChange={(event) => setCatalogSearch(event.target.value)} />
                  <div className="max-h-[50vh] overflow-y-auto">
                    {filteredCatalog.map((model) => {
                      const details = modelDetails(model);
                      const enabled = selected.includes(model.value);
                      return <label key={model.value} className="flex items-center gap-3 border-b py-3" style={{ borderColor: "var(--line)" }}>
                        <ProviderIcon provider={details.provider} />
                        <span className="min-w-0 flex-1"><span className="block text-[0.84rem] font-medium">{model.label}</span><span className="block text-[0.72rem]" style={{ color: "var(--ink-3)" }}>{details.provider}{details.context && ` · ${details.context} context`}{details.input && ` · ${details.input} input / 1M`}{details.output && ` · ${details.output} output / 1M`}</span></span>
                        {enabled ? <span className="text-[0.72rem]" style={{ color: "var(--ink-3)" }}>Already enabled</span> : <input type="checkbox" aria-label={model.label} checked={toAdd.includes(model.value)} onChange={() => setToAdd((current) => current.includes(model.value) ? current.filter((item) => item !== model.value) : [...current, model.value])} />}
                      </label>;
                    })}
                    {filteredCatalog.length === 0 && <p className="text-sm">No models match.</p>}
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3"><span className="text-[0.8rem]" style={{ color: "var(--ink-3)" }}>{toAdd.length} selected</span><div className="flex gap-2"><button type="button" className="af-btn" onClick={() => setDialogOpen(false)}>Cancel</button><button type="button" className="af-btn af-btn-primary" disabled={!toAdd.length} onClick={() => { setSelectedDraft([...new Set([...selected, ...toAdd])]); setDialogOpen(false); }}>Add {toAdd.length} {toAdd.length === 1 ? "model" : "models"}</button></div></div>
                </DialogContent>
              </Dialog>
            </>
          )}
        </div>
      )}
    </SettingsSection>
  );
}
