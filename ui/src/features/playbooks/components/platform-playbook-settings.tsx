"use client";

import { AppErrorState } from "@/components/app-error-state";
import { ModelSettingCard } from "@/components/settings/model-setting-card";

import { usePlatformPlaybookSettings } from "../hooks/use-platform-playbook-settings";

export function PlatformPlaybookSettings() {
  const {
    settings,
    isLoadingSettings,
    settingsError,
    reloadSettings,
    availableModels,
    isLoadingModels,
    modelsError,
    reloadModels,
    saveModel,
    isSavingModel,
    saveError,
    resetSave,
  } = usePlatformPlaybookSettings();
  if (isLoadingSettings) return <p className="m-0">Loading Playbook settings…</p>;
  if (settingsError)
    return (
      <AppErrorState
        error={settingsError}
        title="Could not load Platform Settings"
        onRetry={() => void reloadSettings()}
      />
    );

  return (
    <>
      <ModelSettingCard
        ariaLabel="Playbook settings"
        fieldLabel="Playbook extraction model"
        fieldId="playbook-model"
        summaryTestId="saved-playbook-model"
        searchPlaceholder="Search playbook models…"
        editHint="New playbook extractions use this model. Runs already in progress finish with their original model."
        savedMessage="Playbook extraction model saved."
        details={[
          { label: "Applies to", value: "All Organizations" },
          { label: "Used for", value: "Turning an Agent's conversations into a playbook draft" },
          { label: "Costs charged to", value: "The Agent the playbook is extracted from" },
        ]}
        currentModel={settings?.model ?? ""}
        availableModels={availableModels}
        isLoadingModels={isLoadingModels}
        modelsError={modelsError}
        reloadModels={reloadModels}
        saveModel={saveModel}
        isSavingModel={isSavingModel}
        saveError={saveError}
        resetSave={resetSave}
      />
      <section className="af-card mt-5 p-5" aria-label="About playbook extraction">
        <h3 className="m-0 text-[0.95rem] font-semibold">About playbook extraction</h3>
        <p className="mb-0 mt-2 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          A run reads up to 50 of an Agent&apos;s recent conversations once and writes a playbook draft. It costs a
          small fraction of what the conversations cost, so a stronger model is usually affordable here. Organization
          model allowlists do not apply.
        </p>
      </section>
    </>
  );
}
