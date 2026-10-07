"use client";

import type { ReactNode } from "react";
import { Info } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function CalculationHint({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`How ${label.toLowerCase()} is calculated`}
          className="af-hover-bg inline-flex shrink-0 rounded p-1 align-middle focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{ color: "var(--ink-4)" }}
        >
          <Info size={14} aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 max-w-[calc(100vw-2rem)] p-4 text-[13px] leading-relaxed"
        aria-label={`${label} calculation`}
      >
        <p className="m-0 font-semibold">{label}</p>
        {children}
      </PopoverContent>
    </Popover>
  );
}
