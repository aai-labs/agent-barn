const VARIANT_STYLES = {
  neutral: { background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" },
  accent: { background: "var(--accent-soft)", color: "var(--accent-ink)", border: "1px solid transparent" },
  ok: { background: "var(--ok-soft)", color: "var(--ok)", border: "1px solid transparent" },
  warn: { background: "var(--warn-soft)", color: "var(--warn)", border: "1px solid transparent" },
  danger: { background: "var(--err-soft)", color: "var(--err)", border: "1px solid transparent" },
} as const;

export type BadgeVariant = keyof typeof VARIANT_STYLES;

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  title?: string;
}

/** Small pill label. Use for source/status/count indicators — not for buttons. */
export function Badge({ children, variant = "neutral", className = "", title }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${className}`}
      style={VARIANT_STYLES[variant]}
      title={title}
    >
      {children}
    </span>
  );
}
