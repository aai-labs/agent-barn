import type { ReactNode } from "react";
import { Check } from "lucide-react";

import { FrameHeading, SplitFrame } from "@/components/split-frame";
import { formatUsd } from "@/features/organizations/spend-limit";

/** Quick start sets up Ava in Telegram; "own" hires an Agent the user configures. */
export type OnboardingPath = "quick" | "own";

function stepsFor(path: OnboardingPath, email: string) {
  return [
    { title: "Signed in", description: email },
    { title: "Choose how to start", description: "Ready-made or your own" },
    path === "own"
      ? { title: "Set up your agent", description: "Template, runtime and model" }
      : { title: "Connect Telegram", description: "Chat with your agent there" },
    { title: "You're ready", description: path === "own" ? "Chat now, add channels later" : "Your agent says hi" },
  ];
}

/**
 * The frame every onboarding step sits in: the steps on the left, the step on the right,
 * its actions in the footer. Signing in is step 1, already done by the time it shows.
 */
export function OnboardingShell({
  step,
  path,
  email,
  creditUsd,
  title,
  subtitle,
  footerStart,
  footerEnd,
  children,
}: {
  step: 1 | 2 | 3;
  path: OnboardingPath;
  email: string;
  creditUsd?: number | null;
  title: string;
  subtitle?: ReactNode;
  footerStart?: ReactNode;
  footerEnd?: ReactNode;
  children?: ReactNode;
}) {
  const steps = stepsFor(path, email);
  return (
    <SplitFrame
      rail={
        <ol className="m-0 flex list-none flex-col p-0" aria-label="Progress">
          {steps.map((item, index) => (
            <li
              key={item.title}
              aria-current={index === step ? "step" : undefined}
              className="relative grid grid-cols-[28px_1fr] gap-x-3 pb-6 last:pb-0"
            >
              {index < steps.length - 1 && (
                <span
                  aria-hidden
                  className="absolute bottom-1 left-[13px] top-8 w-0.5 rounded-full"
                  style={{ background: index < step ? "var(--ink)" : "var(--line-strong)" }}
                />
              )}
              <StepNumber index={index} step={step} />
              <span
                className="pt-[3px] text-[13.5px] font-semibold"
                style={{ color: index <= step ? "var(--ink)" : "var(--ink-4)" }}
              >
                {item.title}
              </span>
              <span
                className="col-start-2 truncate text-[12px]"
                style={{ color: index === step ? "var(--ink-3)" : "var(--ink-4)" }}
              >
                {item.description}
              </span>
            </li>
          ))}
        </ol>
      }
      railCompact={
        <ol className="m-0 flex list-none gap-1.5 p-0" aria-hidden>
          {steps.map((item, index) => (
            <li key={item.title}>
              <StepNumber index={index} step={step} small />
            </li>
          ))}
        </ol>
      }
      railFooter={
        creditUsd != null && (
          <div
            className="rounded-xl border px-3 py-3 text-[12px]"
            style={{ background: "var(--bg-elev)", borderColor: "var(--line)", color: "var(--ink-3)" }}
          >
            <b className="mb-0.5 block text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
              Free trial
            </b>
            {formatUsd(creditUsd)} credit
          </div>
        )
      }
      footer={
        <>
          {footerStart}
          <div className="ml-auto flex items-center gap-2.5">{footerEnd}</div>
        </>
      }
    >
      <FrameHeading kicker={`Step ${step + 1} of ${steps.length}`} title={title}>
        {subtitle}
      </FrameHeading>
      {children}
    </SplitFrame>
  );
}

function StepNumber({ index, step, small = false }: { index: number; step: number; small?: boolean }) {
  const done = index < step;
  const current = index === step;
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full border-[1.5px] font-semibold ${small ? "size-[22px] text-[11px]" : "size-7 text-[12.5px]"}`}
      style={{
        background: done ? "var(--ink)" : "var(--bg-elev)",
        borderColor: done || current ? "var(--ink)" : "var(--line-strong)",
        color: done ? "var(--bg-elev)" : current ? "var(--ink)" : "var(--ink-4)",
        boxShadow: current && !small ? "0 0 0 4px var(--bg-sunken)" : undefined,
      }}
    >
      {done ? <Check width={13} height={13} strokeWidth={3} aria-hidden /> : index + 1}
    </span>
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

/** A spinner line for work the page is waiting on. */
export function StepStatus({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 flex items-center gap-2 text-[13.5px]" role="status" style={{ color: "var(--ink-2)" }}>
      <span
        aria-hidden
        className="size-3.5 shrink-0 animate-spin rounded-full border-2"
        style={{ borderColor: "var(--line-strong)", borderTopColor: "var(--ink-2)" }}
      />
      {children}
    </p>
  );
}
