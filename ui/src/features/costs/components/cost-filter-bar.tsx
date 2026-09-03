"use client";

import type { ReactNode } from "react";

import { SearchInput } from "@/components/search-input";

import { COST_PERIODS, COST_SORT_LABELS } from "../constants";
import { CostSortDirectionSchema, type CostFilterOption } from "../schemas";
import { CostOptionCombobox } from "./cost-option-combobox";

export interface CostFilterBarValues {
  q: string;
  agentId: string;
  model: string;
  period: string;
  sort: string;
}

interface CostFilterBarProps {
  values: CostFilterBarValues;
  agentOptions: CostFilterOption[];
  modelOptions: CostFilterOption[];
  onChange: (key: keyof CostFilterBarValues, value: string | null) => void;
  hasActiveFilters: boolean;
  onClear: () => void;
  /** Slot for the organization picker, which only the platform surface has. */
  organizationFilter?: ReactNode;
}

export function CostFilterBar({
  values,
  agentOptions,
  modelOptions,
  onChange,
  hasActiveFilters,
  onClear,
  organizationFilter,
}: CostFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 mb-4">
      <SearchInput
        initialValue={values.q}
        onSearch={(value) => onChange("q", value)}
        placeholder="Search by model, agent, or request ID"
        className="min-w-64 flex-1"
      />

      {organizationFilter}

      <CostOptionCombobox
        options={agentOptions}
        value={values.agentId || null}
        onChange={(option) => onChange("agentId", option?.value ?? null)}
        placeholder="All agents"
        emptyLabel="No agents with spend"
        testId="cost-agent-filter"
      />

      <CostOptionCombobox
        options={modelOptions}
        value={values.model || null}
        onChange={(option) => onChange("model", option?.value ?? null)}
        placeholder="All models"
        emptyLabel="No models with spend"
        width="13rem"
        testId="cost-model-filter"
      />

      <select
        className="af-input"
        style={{ width: "9.5rem" }}
        aria-label="Period"
        data-testid="cost-period-filter"
        value={values.period}
        onChange={(e) => onChange("period", e.target.value)}
      >
        {COST_PERIODS.map((period) => (
          <option key={period.value} value={period.value}>
            {period.label}
          </option>
        ))}
      </select>

      <select
        className="af-input"
        style={{ width: "10rem" }}
        aria-label="Sort"
        data-testid="cost-sort-filter"
        value={values.sort}
        onChange={(e) => onChange("sort", e.target.value)}
      >
        {CostSortDirectionSchema.options.map((sort) => (
          <option key={sort} value={sort}>
            {COST_SORT_LABELS[sort]}
          </option>
        ))}
      </select>

      {hasActiveFilters && (
        <button type="button" className="af-btn" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}
