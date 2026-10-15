"use client";

import type { ReactNode } from "react";
import { ArrowRight, Check, Info, Wrench, Zap } from "lucide-react";

import type { OnboardingPath } from "./onboarding-shell";

/** The body of step 2: a ready-made assistant in Telegram, or an Agent of their own. */
export function ChooseStep({
  path,
  onPathChange,
  agentLimit,
}: {
  path: OnboardingPath;
  onPathChange: (path: OnboardingPath) => void;
  agentLimit: number | null;
}) {
  return (
    <>
      <div role="radiogroup" aria-label="How to start" className="grid gap-3 sm:grid-cols-2">
        <Option
          selected={path === "quick"}
          onSelect={() => onPathChange("quick")}
          icon={<Zap width={16} height={16} />}
          title="Quick start"
          badge="Recommended"
          description="We set up a general-purpose assistant for you. Chat with it in Telegram in under a minute."
          points={["Ready to go, nothing to configure", "Chat in Telegram or on the web"]}
        />
        <Option
          selected={path === "own"}
          onSelect={() => onPathChange("own")}
          icon={<Wrench width={16} height={16} />}
          title="Build my own agent"
          description="Choose its template, runtime and model yourself."
          points={["Hermes or OpenClaw, any template", "Chat on the web; add Telegram, Slack or Discord later"]}
        />
      </div>
      {agentLimit != null && (
        <p
          className="mb-0 mt-4 flex gap-2 rounded-[10px] px-3 py-2.5 text-[12.5px]"
          style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
        >
          <Info width={14} height={14} className="mt-0.5 shrink-0" aria-hidden />
          {agentLimit === 1
            ? "Your trial has room for one agent. To try something else later, delete it and hire another."
            : `Your trial has room for ${agentLimit} agents.`}
        </p>
      )}
    </>
  );
}

export function ContinueButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="af-btn af-btn-primary af-btn-lg" onClick={onClick}>
      Continue
      <ArrowRight aria-hidden />
    </button>
  );
}

function Option({
  selected,
  onSelect,
  icon,
  title,
  badge,
  description,
  points,
}: {
  selected: boolean;
  onSelect: () => void;
  icon: ReactNode;
  title: string;
  badge?: string;
  description: string;
  points: string[];
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className="af-hover-bg flex flex-col gap-1.5 rounded-[14px] border p-[18px] text-left"
      style={{
        borderColor: selected ? "var(--ink)" : "var(--line-strong)",
        boxShadow: selected ? "0 0 0 3px var(--bg-sunken)" : undefined,
        background: selected ? "var(--bg-elev)" : undefined,
      }}
    >
      <span className="mb-1.5 flex w-full items-center">
        <span
          aria-hidden
          className="grid size-9 place-items-center rounded-[10px] border"
          style={{ background: "var(--bg-soft)", borderColor: "var(--line)", color: "var(--ink-2)" }}
        >
          {icon}
        </span>
        <span
          aria-hidden
          className="ml-auto grid size-4 place-items-center rounded-full border-[1.5px]"
          style={{ borderColor: selected ? "var(--ink)" : "var(--line-strong)" }}
        >
          {selected && <span className="size-2 rounded-full" style={{ background: "var(--ink)" }} />}
        </span>
      </span>
      <span className="flex items-center gap-2 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
        {title}
        {badge && (
          <span
            className="rounded-full px-2 text-[11px] font-medium"
            style={{ background: "var(--accent-soft)", color: "var(--accent-ink)" }}
          >
            {badge}
          </span>
        )}
      </span>
      <span className="text-[13px]" style={{ color: "var(--ink-3)" }}>
        {description}
      </span>
      <span className="mt-1.5 flex flex-col gap-1 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
        {points.map((point) => (
          <span key={point} className="flex items-start gap-1.5">
            <Check width={13} height={13} className="mt-[3px] shrink-0" style={{ color: "var(--ok)" }} aria-hidden />
            {point}
          </span>
        ))}
      </span>
    </button>
  );
}
