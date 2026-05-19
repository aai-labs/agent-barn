import { SearchIcon } from "@/components/icons";

interface ListPageHeaderProps {
  title: string;
  description: string;
  count: number;
  noun: string;
  search: string;
  onSearch: (value: string) => void;
  searchPlaceholder?: string;
}

export function ListPageHeader({
  title,
  description,
  count,
  noun,
  search,
  onSearch,
  searchPlaceholder,
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
        <div className="relative w-full md:w-72">
          <SearchIcon
            size={14}
            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
            style={{ color: "var(--ink-4)" }}
          />
          <input
            className="af-input pl-8"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={searchPlaceholder ?? `Search ${noun}s`}
            aria-label={`Search ${noun}s`}
          />
        </div>
      </div>
      <p className="text-[13px] mb-4" style={{ color: "var(--ink-4)" }}>
        {countLabel}
      </p>
    </>
  );
}
