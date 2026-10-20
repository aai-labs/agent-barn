"use client";

/** Previous/Next paging for a server-paginated workflow collection. */
export function WorkflowPager({
  page,
  pageSize,
  total,
  onChange,
  noun,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  /** Appended to the button labels, e.g. "versions". */
  noun?: string;
}) {
  if (page > Math.max(1, Math.ceil(total / pageSize)))
    return (
      <button className="af-btn my-3" onClick={() => onChange(1)}>
        Return to first page
      </button>
    );
  if (total <= pageSize) return null;
  const suffix = noun ? ` ${noun}` : "";
  return (
    <div className="flex items-center gap-3 my-3">
      <button
        className="af-btn"
        disabled={page === 1}
        onClick={() => onChange(page - 1)}
      >
        Previous{suffix}
      </button>
      <span>Page {page}</span>
      <button
        className="af-btn"
        disabled={page * pageSize >= total}
        onClick={() => onChange(page + 1)}
      >
        Next{suffix}
      </button>
    </div>
  );
}
