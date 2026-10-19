import type { ReactNode } from "react";
import Link from "next/link";

import { FrameHeading, SplitFrame } from "@/components/split-frame";

const PITCH = [
  { mark: "✦", text: "Hire agents from templates, on Hermes or OpenClaw" },
  { mark: "✉", text: "Chat on the Slack, Telegram, Teams, Discord and more." },
  { mark: "$", text: "See what they do and what they spend" },
];

/** The frame of every signed-out page: welcome, forgot, reset and set password. */
export function AuthFrame({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <SplitFrame
      centered
      rail={
        <div className="flex flex-col gap-4">
          <h2 className="m-0 text-[19px] font-semibold leading-snug tracking-tight" style={{ color: "var(--ink)" }}>
            Your AI agents, at work.
          </h2>
          <ul className="m-0 flex list-none flex-col gap-3 p-0 text-[13px]" style={{ color: "var(--ink-2)" }}>
            {PITCH.map((item) => (
              <li key={item.text} className="flex items-start gap-2.5">
                <span
                  aria-hidden
                  className="grid size-6 shrink-0 place-items-center rounded-lg border text-[12px]"
                  style={{ background: "var(--bg-elev)", borderColor: "var(--line)" }}
                >
                  {item.mark}
                </span>
                {item.text}
              </li>
            ))}
          </ul>
        </div>
      }
      railFooter={
        <span className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
          Free trial · no card needed
        </span>
      }
      footer={
        <p className="m-0 text-center text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          By continuing you agree to the{" "}
          <Link href="#" style={{ color: "var(--ink-3)" }}>
            Terms
          </Link>{" "}
          and{" "}
          <Link href="#" style={{ color: "var(--ink-3)" }}>
            Privacy Policy
          </Link>
          .
        </p>
      }
    >
      <FrameHeading centered title={title}>
        {subtitle}
      </FrameHeading>
      {children}
    </SplitFrame>
  );
}

/** A labelled input with its error, as the signed-out forms lay them out. */
export function AuthField({
  id,
  label,
  error,
  aside,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label htmlFor={id} className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
          {label}
        </label>
        {aside}
      </div>
      {children}
      {error && (
        <p className="mb-0 mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
