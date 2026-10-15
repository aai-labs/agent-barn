"use client";

import { useState } from "react";

import { AppErrorState } from "@/components/app-error-state";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { usePlatformWorkflowSettings } from "../hooks/use-platform-workflow-settings";

export function PlatformWorkflowSettings() {
  const {
    settings, isLoading, error, reload, save, isSaving, saveError, resetSave,
  } = usePlatformWorkflowSettings();
  const [draft, setDraft] = useState<boolean | null>(null);
  const [saved, setSaved] = useState(false);
  if (isLoading) return <p role="status">Loading workflow settings…</p>;
  if (error)
    return (
      <AppErrorState
        error={error}
        title="Could not load workflow settings"
        onRetry={() => void reload()}
      />
    );
  const enabled = draft ?? settings?.authoringEnabled ?? false;
  const changed = enabled !== settings?.authoringEnabled;
  async function submit() {
    try {
      await save(enabled);
      setDraft(null);
      setSaved(true);
    } catch {
      // Preserve the choice beside the retryable save error.
    }
  }
  return (
    <section className="af-card overflow-hidden" aria-label="Workflow settings">
      <div className="p-5">
        <div className="flex items-center justify-between gap-4">
          <h3 id="workflow-authoring-label" className="m-0 text-sm font-medium">
            Enable workflow authoring
          </h3>
          <button
            type="button"
            role="switch"
            aria-labelledby="workflow-authoring-label"
            aria-describedby="workflow-authoring-description"
            aria-checked={enabled}
            disabled={isSaving}
            onClick={() => {
              setDraft(!enabled);
              setSaved(false);
              resetSave();
            }}
            className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: enabled ? "var(--ink)" : "var(--line)" }}
          >
            <span
              className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${enabled ? "translate-x-4" : ""}`}
            />
          </button>
        </div>
        <p
          id="workflow-authoring-description"
          className="mt-3 text-sm"
          style={{ color: "var(--ink-3)" }}
        >
          Allow Editors to create, save versions and archive workflows across all
          Organizations. Changes apply when saved. Disabling hides Workflows from
          Agent pages and preserves saved workflows.
        </p>
        <p className="text-sm" style={{ color: "var(--ink-3)" }}>
          Workflow execution is unavailable.
        </p>
        {saveError && (
          <p
            role="alert"
            aria-label="Workflow setting error"
            className="mt-3 text-sm"
            style={{ color: "var(--danger)" }}
          >
            {getErrorDisplay(saveError).description}
          </p>
        )}
        {saved && (
          <p role="status" className="mt-3 text-sm">Workflow settings saved.</p>
        )}
      </div>
      <footer
        className="flex justify-end gap-2 border-t px-5 py-3"
        style={{ borderColor: "var(--line)" }}
      >
        <button
          className="af-btn"
          disabled={!changed || isSaving}
          onClick={() => {
            setDraft(null);
            setSaved(false);
            resetSave();
          }}
        >
          Cancel
        </button>
        <button
          className="af-btn af-btn-primary"
          disabled={!changed || isSaving}
          onClick={() => void submit()}
        >
          {isSaving ? "Saving…" : "Save"}
        </button>
      </footer>
    </section>
  );
}
