"use client";

import { AppErrorState } from "@/components/app-error-state";
import { ModelSettingCard } from "@/components/settings/model-setting-card";

import { usePlatformMemorySettings } from "../hooks/use-platform-memory-settings";

export function PlatformMemorySettings() {
  const {
    memorySettings,
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
  } = usePlatformMemorySettings();
  if (isLoadingSettings) return <div>Loading Platform Settings…</div>;
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
        ariaLabel="Agent Memory settings"
        fieldLabel="Memory processing model"
        fieldId="memory-model"
        summaryTestId="saved-memory-model"
        searchPlaceholder="Search memory models…"
        editHint="Changes apply to new memory work within five seconds. Work already in progress finishes with its original model."
        savedMessage="Memory processing model saved."
        details={[
          { label: "Applies to", value: "All Agents and Organizations" },
          { label: "Used for", value: "Fact extraction, observations, and reflection" },
          { label: "Costs charged to", value: "The Organization using memory" },
        ]}
        currentModel={memorySettings?.model ?? ""}
        availableModels={availableModels}
        isLoadingModels={isLoadingModels}
        modelsError={modelsError}
        reloadModels={reloadModels}
        saveModel={saveModel}
        isSavingModel={isSavingModel}
        saveError={saveError}
        resetSave={resetSave}
      />
      <section className="af-card mt-5 p-5" aria-label="About memory processing">
        <h3 className="m-0 text-[0.95rem] font-semibold">About memory processing</h3>
        <p className="mb-0 mt-2 text-[0.84rem] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          Each Agent keeps its own chat model. This model processes long-term memories across the platform. Changing
          it preserves saved memories and applies to new memory work within five seconds.
        </p>
      </section>
    </>
  );
}
