import type { ReactNode } from "react";

import { SearchInput } from "@/components/search-input";

interface ListPageHeaderProps {
  title: string;
  description: string;
  count: number;
  noun: string;
  /** Receives the debounced search value. */
  onSearch: (value: string) => void;
  searchPlaceholder?: string;
  action?: ReactNode;
}

export function ListPageHeader({
  title,
  description,
  count,
  noun,
  onSearch,
  searchPlaceholder,
  action,
}: ListPageHeaderProps) {
  const countLabel = `${count} ${count === 1 ? noun : noun + "s"}`;

  return (
    <>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between mb-8">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight m-0 mb-1" style={{ color: "var(--ink)" }}>
            {title}
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            {description}
          </p>
        </div>
        <div className="flex items-center gap-2.5 w-full md:w-auto">
          <SearchInput
            onSearch={onSearch}
            placeholder={searchPlaceholder ?? `Search ${noun}s`}
            ariaLabel={`Search ${noun}s`}
            className="flex-1 md:w-72 md:flex-none"
          />
          {action}
        </div>
      </div>
      <p className="text-[13px] mb-4" style={{ color: "var(--ink-4)" }}>
        {countLabel}
      </p>
    </>
  );
}
