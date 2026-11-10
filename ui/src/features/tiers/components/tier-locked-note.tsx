import { Lock } from "lucide-react";

/** Said where a control is missing because the organization's tier leaves it out. */
export function TierLockedNote({ tierName, what }: { tierName?: string | null; what: string }) {
  return (
    <p className="m-0 flex items-center gap-1.5 text-sm" style={{ color: "var(--ink-3)" }}>
      <Lock size={14} aria-hidden />
      {tierName ? `Your organization's tier, ${tierName}, doesn't include ${what}.` : `Your organization's tier doesn't include ${what}.`}
    </p>
  );
}
