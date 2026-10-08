import type { ReactNode } from "react";

import { LogoMark } from "@/components/logo-mark";

const STEPS = ["Sign in", "Telegram", "Done"] as const;

/** The frame every onboarding step sits in: brand, progress, and one centred card. */
export function OnboardingShell({ step, children }: { step: 1 | 2 | 3; children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col" style={{ background: "var(--bg)" }}>
      <header
        className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <div className="flex items-center gap-2.5">
          <LogoMark size={28} />
          <span className="text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            Agent Barn
          </span>
        </div>
        <div className="ml-auto flex items-center gap-4">
          <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Step {step} of {STEPS.length}
          </span>
          <ol className="m-0 flex list-none gap-2 p-0" aria-label="Progress">
            {STEPS.map((label, index) => (
              <li key={label} className="flex flex-col gap-1">
                <span
                  aria-hidden
                  className="block h-1 w-12 rounded-full sm:w-16"
                  style={{ background: index < step ? "var(--ink)" : "var(--line)" }}
                />
                <span className="text-[11.5px]" style={{ color: index < step ? "var(--ink-2)" : "var(--ink-4)" }}>
                  {label}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-10 sm:py-16">
        <section
          className="w-full max-w-md rounded-2xl px-6 py-8 sm:px-8"
          style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
        >
          {children}
        </section>
      </main>
    </div>
  );
}

export function StepHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="m-0 text-[22px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
        {title}
      </h1>
      {children && (
        <p className="mb-0 mt-2 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {children}
        </p>
      )}
    </div>
  );
}

export function StepAlert({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="m-0 rounded-lg px-3 py-2.5 text-[13px]"
      style={{ background: "var(--err-soft)", color: "var(--err)" }}
    >
      {children}
    </p>
  );
}
