/**
 * The word "limit" after a limit figure, in the same quiet type as the "requests ..." line,
 * so a number beside a usage is never left for the reader to guess at.
 */
export function LimitLabel() {
  return (
    <span className="text-[12px] font-normal" style={{ color: "var(--ink-4)" }} data-testid="limit-label">
      {" limit"}
    </span>
  );
}
