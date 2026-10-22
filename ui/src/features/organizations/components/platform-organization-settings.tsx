"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useOrganizationSettings } from "../hooks/use-organization-settings";

// The API's bound: it only stops a typo.
const MAX_DEFAULT_AGENT_LIMIT = 1000;

function agentsLabel(count: number) {
  return `${count} ${count === 1 ? "agent" : "agents"}`;
}

function parseLimit(raw: string): number | null {
  const parsed = Number(raw.trim());
  return raw.trim() !== "" && Number.isInteger(parsed) && parsed >= 1 && parsed <= MAX_DEFAULT_AGENT_LIMIT
    ? parsed
    : null;
}

/** The Organizations section of the platform settings page: what every organization gets. */
export function PlatformOrganizationSettings() {
  const { organizationSettings, isLoading, error, reload, saveSettings, isSaving, saveError, resetSave } =
    useOrganizationSettings();
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (isLoading) return <p className="m-0">Loading organization settings…</p>;
  if (error || !organizationSettings)
    return <AppErrorState error={error} title="Could not load organization settings" onRetry={() => void reload()} />;

  const limit = draft === null ? null : parseLimit(draft);
  const invalid = draft !== null && limit === null;

  async function submit() {
    if (limit === null) return;
    try {
      await saveSettings({ defaultAgentLimit: limit });
      setDraft(null);
      setSaved(true);
    } catch {
      /* The error stays beside the field. */
    }
  }

  return (
    <section className="af-card overflow-hidden" aria-label="Organization settings">
      <div className="p-5">
        {draft !== null ? (
          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="default-agent-limit">
              Default agent limit
            </label>
            <input
              id="default-agent-limit"
              inputMode="numeric"
              className="af-input max-w-[8rem]"
              value={draft}
              aria-invalid={invalid}
              onChange={(event) => {
                setDraft(event.target.value);
                setSaved(false);
                resetSave();
              }}
            />
            {invalid && (
              <p className="mt-2 text-sm" style={{ color: "var(--err)" }}>
                Enter a whole number from 1 to 1,000.
              </p>
            )}
            <p className="mb-0 mt-2 text-sm" style={{ color: "var(--ink-3)" }}>
              How many agents an organization may run, unless you&apos;ve set its own limit. Trials follow the
              trial setting instead. An organization already over a lower limit keeps its agents but can&apos;t
              hire more.
            </p>
          </div>
        ) : (
          <dl className="m-0">
            <dt
              className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.08em]"
              style={{ color: "var(--ink-4)" }}
            >
              Default agent limit
            </dt>
            <dd className="m-0 text-[0.9rem]">{agentsLabel(organizationSettings.defaultAgentLimit)}</dd>
          </dl>
        )}
        {saveError && (
          <p className="mt-3 text-sm" role="alert" style={{ color: "var(--err)" }}>
            {getErrorDisplay(saveError).description}
          </p>
        )}
        {saved && (
          <p className="mb-0 mt-3 text-sm" role="status">
            Organization settings saved.
          </p>
        )}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--line)" }}>
        {draft !== null ? (
          <>
            <button
              className="af-btn"
              disabled={isSaving}
              onClick={() => {
                setDraft(null);
                resetSave();
              }}
            >
              Cancel
            </button>
            <button className="af-btn af-btn-primary" disabled={invalid || isSaving} onClick={() => void submit()}>
              {isSaving ? "Saving…" : "Save"}
            </button>
          </>
        ) : (
          <button
            className="af-btn"
            onClick={() => {
              setDraft(String(organizationSettings.defaultAgentLimit));
              setSaved(false);
            }}
          >
            <Pencil size={14} /> Edit
          </button>
        )}
      </footer>
    </section>
  );
}
