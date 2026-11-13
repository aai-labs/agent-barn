"use client";

import { AppErrorState } from "@/components/app-error-state";
import { ModelSettingCard } from "@/components/settings/model-setting-card";

import { usePlatformDecisionSettings } from "../hooks/use-platform-decision-settings";

export function PlatformDecisionSettings() {
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
  } = usePlatformDecisionSettings();
  if (isLoadingSettings) return <p className="m-0">Loading Decision settings…</p>;
  if (settingsError)
    return (
      <AppErrorState
        error={settingsError}
        title="Could not load Platform Settings"
        onRetry={() => void reloadSettings()}
      />
    );

  return (
    <ModelSettingCard
      ariaLabel="Decision settings"
      fieldLabel="Decision model"
      fieldId="decision-model"
      summaryTestId="saved-decision-model"
      searchPlaceholder="Search decision models…"
      editHint="Questions asked from now on use this model."
      savedMessage="Decision model saved."
      details={[
        { label: "Applies to", value: "All Organizations" },
        { label: "Used for", value: "Yes/no, choice and score questions the platform asks about an Agent" },
        { label: "Costs charged to", value: "The Agent the question is about" },
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
  );
}
