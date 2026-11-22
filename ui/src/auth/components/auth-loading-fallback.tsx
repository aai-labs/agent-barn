import type { CSSProperties } from "react";

// The pixel barn of `LogoMark`, one string per row, top to bottom: `#` is a filled cell.
const BARN = [
  "..###..",
  ".#####.",
  "#######",
  "#######",
  "##....#",
  "#######",
  "##....#",
];

// Built from the ground up: bottom row first, each row left to right.
const CELLS = BARN.flatMap((row, y) =>
  [...row].flatMap((cell, x) => (cell === "#" ? [{ x, y }] : [])),
).sort((a, b) => b.y - a.y || a.x - b.x);

const STEP_MS = 30;

/**
 * The full-page screen shown while the app gets the account and organizations ready, or
 * hands off to the login page. While `busy`, the barn builds itself pixel by pixel and
 * dissolves in the same order, over a faint outline of the finished mark; otherwise (an
 * error) it stands still.
 */
export function AuthLoadingFallback({ message, busy = true }: { message: string; busy?: boolean }) {
  return (
    <div
      role="status"
      aria-busy={busy}
      className="flex min-h-svh flex-col items-center justify-center gap-5 p-6"
      style={{ background: "var(--bg)" }}
    >
      <svg viewBox="-0.5 -0.5 8 8" width={64} height={64} aria-hidden className="af-barn-build" data-busy={busy}>
        {CELLS.map(({ x, y }, index) => (
          <g key={`${x}-${y}`}>
            <rect x={x + 0.05} y={y + 0.05} width={0.9} height={0.9} className="af-barn-ghost" />
            <rect
              x={x + 0.05}
              y={y + 0.05}
              width={0.9}
              height={0.9}
              className="af-barn-cell"
              style={{ "--af-barn-delay": `${index * STEP_MS}ms` } as CSSProperties}
            />
          </g>
        ))}
      </svg>
      <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
        {message}
      </p>
    </div>
  );
}
