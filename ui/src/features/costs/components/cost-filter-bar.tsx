"use client";

import { memo, type ReactNode } from "react";

import { DateRangePicker } from "@/components/date-range-picker";
import { SearchInput } from "@/components/search-input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { COST_SORT_LABELS } from "../constants";
import { CostSortDirectionSchema, type CostFilterOption } from "../schemas";
import { CostOptionCombobox } from "./cost-option-combobox";

export interface CostFilterBarValues {
  q: string;
  agentId?: string;
  model: string;
  /** ISO datetime bounds, or "" for "let the server pick the window". */
  from: string;
  to: string;
  sort: string;
}

interface CostFilterBarProps {
  values: CostFilterBarValues;
  /** Omit to drop the agent picker, on a surface that is already one Agent's. */
  agentOptions?: CostFilterOption[];
  modelOptions: CostFilterOption[];
  onChange: (key: keyof CostFilterBarValues, value: string | null) => void;
  /** Both bounds move together: two single-key updates would race, because each
   *  reads the same query string and the second would drop the first. */
  onDateRangeChange: (from: string, to: string) => void;
  hasActiveFilters: boolean;
  onClear: () => void;
  /** Slot for the organization picker, which only the platform surface has. */
  organizationFilter?: ReactNode;
  searchPlaceholder?: string;
  /** What the date picker says while no range is picked. */
  datePlaceholder?: string;
  /** Drop the sort control where the list it orders carries its own. */
  showSort?: boolean;
}

/** Memoised: the pages above re-render whenever Next's router context changes,
 *  and re-rendering this bar remounts the comboboxes' portals and rewrites the
 *  search box's attributes for no reason. Its props are all stable references. */
export const CostFilterBar = memo(function CostFilterBar({
  values,
  agentOptions,
  modelOptions,
  onChange,
  onDateRangeChange,
  hasActiveFilters,
  onClear,
  organizationFilter,
  searchPlaceholder = "Search by model, agent, or request ID",
  datePlaceholder = "All dates",
  showSort = true,
}: CostFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 mb-4">
      <SearchInput
        initialValue={values.q}
        onSearch={(value) => onChange("q", value)}
        placeholder={searchPlaceholder}
        className="min-w-64 flex-1"
      />

      {organizationFilter}

      {agentOptions && (
        <CostOptionCombobox
          options={agentOptions}
          value={values.agentId || null}
          onChange={(option) => onChange("agentId", option?.value ?? null)}
          placeholder="All agents"
          emptyLabel="No agents with spend"
          testId="cost-agent-filter"
        />
      )}

      <CostOptionCombobox
        options={modelOptions}
        value={values.model || null}
        onChange={(option) => onChange("model", option?.value ?? null)}
        placeholder="All models"
        emptyLabel="No models with spend"
        width="13rem"
        testId="cost-model-filter"
      />

      <DateRangePicker
        from={values.from}
        to={values.to}
        onChange={onDateRangeChange}
        placeholder={datePlaceholder}
        width="16rem"
        ariaLabel="Date range"
      />

      {showSort && (
        <CostSortSelect
          value={values.sort}
          onChange={(value) => onChange("sort", value)}
        />
      )}

      {hasActiveFilters && (
        <button type="button" className="af-btn" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
});

export function CostSortSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        className="af-input !h-auto"
        style={{ width: "10rem" }}
        aria-label="Sort"
        data-testid="cost-sort-filter"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {CostSortDirectionSchema.options.map((sort) => (
            <SelectItem key={sort} value={sort}>
              {COST_SORT_LABELS[sort]}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
