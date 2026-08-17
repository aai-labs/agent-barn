import { PlugZap } from "lucide-react";

import { SKILL_PROVIDER_LABELS } from "../utils";

// Deterministic per-provider accent so the list reads as a set of distinct
// integrations rather than one undifferentiated block of pills.
const ACCENTS = [
  "linear-gradient(135deg, #4338ca, #7c3aed)",
  "linear-gradient(135deg, #0d9488, #15803d)",
  "linear-gradient(135deg, #b45309, #c2410c)",
  "linear-gradient(135deg, #be185d, #9d174d)",
  "linear-gradient(135deg, #0369a1, #1d4ed8)",
];

function accentFor(provider: string): string {
  let hash = 0;
  for (let i = 0; i < provider.length; i++) hash = (hash * 31 + provider.charCodeAt(i)) >>> 0;
  return ACCENTS[hash % ACCENTS.length];
}

/** The tools/integrations a skill needs credentials for — styled as a small
 * roster rather than generic filter pills, since these are load-bearing
 * requirements (an agent can't use the skill without them), not metadata. */
export function SkillRequiredProviders({ providers }: { providers: string[] }) {
  if (providers.length === 0) {
    return (
      <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>
        No integrations required.
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {providers.map((provider) => (
        <div
          key={provider}
          className="flex items-center gap-2 rounded-xl px-3 py-2"
          style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
        >
          <div
            className="w-7 h-7 rounded-lg grid place-items-center flex-shrink-0"
            style={{ background: accentFor(provider) }}
          >
            <PlugZap size={13} color="#fff" />
          </div>
          <span className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
            {SKILL_PROVIDER_LABELS[provider] ?? provider}
          </span>
        </div>
      ))}
    </div>
  );
}
