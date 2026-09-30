import { Fragment } from "react";

/**
 * Splits an API error detail into prose and identifier runs.
 *
 * These messages quote model slugs and nothing else — Agent names are deliberately
 * left bare — so a single-quoted run is a reliable signal for "this is an identifier
 * the reader may need to copy", not emphasis.
 */
function splitQuoted(message: string) {
  return message
    .split(/'([^']+)'/g)
    .map((text, index) => ({ text, isIdentifier: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

/**
 * The inline failure message for a settings section. Sections that render this are
 * the same ones that suppress the Apply toast, so the error is stated once.
 */
export function SettingsErrorText({ children }: { children: string }) {
  return (
    <span className="text-xs" style={{ color: "var(--err)" }}>
      {splitQuoted(children).map((part, index) =>
        part.isIdentifier ? (
          <code
            key={index}
            className="rounded px-1 py-0.5 font-mono text-[0.72rem]"
            style={{ background: "var(--err-soft)" }}
          >
            {part.text}
          </code>
        ) : (
          <Fragment key={index}>{part.text}</Fragment>
        ),
      )}
    </span>
  );
}
