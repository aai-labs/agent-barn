"use client";

import React from "react";

import { formatAction } from "../utils";

export type OrgOption = { id: string; name: string };

export type DraftFilters = {
  action: string;
  search: string;
  startDate: string;
  endDate: string;
  organizationId: string; // "" = all organizations (superuser view only)
};

const EMPTY: DraftFilters = {
  action: "",
  search: "",
  startDate: "",
  endDate: "",
  organizationId: "",
};

const inputStyle = {
  border: "1px solid var(--line-strong)",
  background: "var(--bg-elev)",
  color: "var(--ink-2)",
};

type Props = {
  actions: string[];
  orgOptions?: OrgOption[];
  onApply: (filters: DraftFilters) => void;
  onExport: () => void;
  isExporting: boolean;
};

export function AuditLogFilters({
  actions,
  orgOptions,
  onApply,
  onExport,
  isExporting,
}: Props) {
  const [draft, setDraft] = React.useState<DraftFilters>(EMPTY);
  const today = new Date().toISOString().split("T")[0];

  const set = (patch: Partial<DraftFilters>) =>
    setDraft((prev) => ({ ...prev, ...patch }));

  const reset = () => {
    setDraft(EMPTY);
    onApply(EMPTY);
  };

  return (
    <div className="af-card px-4 py-3 mb-6 flex flex-wrap items-end gap-3">
      {orgOptions && (
        <Field label="Organization">
          <select
            className="af-select"
            style={{ minWidth: 180 }}
            value={draft.organizationId}
            onChange={(e) => set({ organizationId: e.target.value })}
          >
            <option value="">All organizations</option>
            {orgOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field label="Action">
        <select
          className="af-select"
          style={{ minWidth: 180 }}
          value={draft.action}
          onChange={(e) => set({ action: e.target.value })}
        >
          <option value="">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {formatAction(a)}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Actor / target">
        <input
          type="text"
          placeholder="email or name…"
          className="text-[0.8125rem] rounded-lg px-3 py-1.5 focus:outline-none"
          style={{ ...inputStyle, minWidth: 180 }}
          value={draft.search}
          onChange={(e) => set({ search: e.target.value })}
        />
      </Field>

      <Field label="From">
        <input
          type="date"
          max={draft.endDate || today}
          className="text-[0.8125rem] rounded-lg px-3 py-1.5 focus:outline-none"
          style={inputStyle}
          value={draft.startDate}
          onChange={(e) => set({ startDate: e.target.value })}
        />
      </Field>

      <Field label="To">
        <input
          type="date"
          min={draft.startDate || undefined}
          max={today}
          className="text-[0.8125rem] rounded-lg px-3 py-1.5 focus:outline-none"
          style={inputStyle}
          value={draft.endDate}
          onChange={(e) => set({ endDate: e.target.value })}
        />
      </Field>

      <div className="flex items-center gap-2 ml-auto">
        <button className="af-btn" onClick={() => onApply(draft)}>
          Apply
        </button>
        <button className="af-btn af-btn-ghost" onClick={reset}>
          Reset
        </button>
        <button
          className="af-btn af-btn-ghost"
          onClick={onExport}
          disabled={isExporting}
        >
          {isExporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="text-[0.6875rem] uppercase tracking-wide font-medium"
        style={{ color: "var(--ink-4)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}
