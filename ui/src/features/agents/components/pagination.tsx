export function Pagination({
  page,
  totalPages,
  onPageChange,
  align = "center",
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  align?: "center" | "end";
}) {
  if (totalPages <= 1) return null;
  return (
    <div className={`flex items-center gap-3 ${align === "end" ? "justify-end" : "justify-center"}`}>
      <button
        className="af-btn af-btn-sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        Previous
      </button>
      <span className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
        {page} / {totalPages}
      </span>
      <button
        className="af-btn af-btn-sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Next
      </button>
    </div>
  );
}
