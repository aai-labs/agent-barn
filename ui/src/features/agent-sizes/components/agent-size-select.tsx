"use client";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { AgentSizeOption } from "../schemas";
import { describeSize } from "../utils";

/**
 * Pick one of the sizes an Organization may choose. `unavailable` is a size an Agent is still
 * on but that can no longer be chosen (withdrawn or disabled): shown so the current value
 * reads truthfully, but not selectable.
 */
export function AgentSizeSelect({
  sizes,
  value,
  onChange,
  unavailable,
  disabled = false,
}: {
  sizes: AgentSizeOption[];
  value: string;
  onChange: (size: AgentSizeOption) => void;
  unavailable?: AgentSizeOption | null;
  disabled?: boolean;
}) {
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(id) => {
        const size = sizes.find((candidate) => candidate.id === id);
        if (size) onChange(size);
      }}
    >
      <SelectTrigger aria-label="CPU & memory" className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {sizes.map((size) => (
            <SelectItem key={size.id} value={size.id}>
              {describeSize(size)}
              {size.isDefault ? " (default)" : ""}
            </SelectItem>
          ))}
          {unavailable && (
            <SelectItem value={unavailable.id} disabled>
              {describeSize(unavailable)} (no longer offered)
            </SelectItem>
          )}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
