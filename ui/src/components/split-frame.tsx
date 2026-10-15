import type { ReactNode } from "react";

import { LogoMark } from "@/components/logo-mark";

/**
 * The two-pane frame of the signed-out and onboarding pages: a rail with the brand on the
 * left, the page on the right, and a footer under it. Below `md` the rail collapses into a
 * top bar showing only the brand and `railCompact`.
 */
export function SplitFrame({
  rail,
  railCompact,
  railFooter,
  footer,
  centered = false,
  children,
}: {
  rail: ReactNode;
  railCompact?: ReactNode;
  railFooter?: ReactNode;
  footer: ReactNode;
  /** Centre the page in one column instead of filling the pane from the top left. */
  centered?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-svh flex-col md:items-center md:justify-center md:p-8" style={{ background: "var(--bg)" }}>
      <div
        className={`flex w-full flex-1 flex-col md:grid md:min-h-[620px] md:flex-none md:grid-cols-[280px_1fr] md:overflow-hidden md:rounded-[20px] md:border md:[box-shadow:var(--shadow)] ${centered ? "md:max-w-[920px]" : "md:max-w-[980px]"}`}
        style={{ background: "var(--bg-elev)", borderColor: "var(--line)" }}
      >
        <aside
          className="flex items-center gap-4 border-b px-3 py-3.5 sm:px-5 md:flex-col md:items-stretch md:gap-8 md:border-b-0 md:border-r md:px-6 md:py-7"
          style={{ background: "var(--bg-soft)", borderColor: "var(--line)" }}
        >
          <div className="flex items-center gap-2.5 whitespace-nowrap">
            <LogoMark size={28} />
            <span className="text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
              Agent Barn
            </span>
          </div>
          <div className="hidden md:block">{rail}</div>
          {railCompact && <div className="ml-auto md:hidden">{railCompact}</div>}
          {railFooter && <div className="mt-auto hidden flex-col gap-2.5 md:flex">{railFooter}</div>}
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <div className={`flex-1 px-6 py-7 md:px-12 ${centered ? "flex items-center justify-center md:py-12" : "md:pb-8 md:pt-11"}`}>
            {centered ? <div className="w-full max-w-[400px]">{children}</div> : children}
          </div>
          <footer
            className={`flex min-h-[68px] flex-wrap items-center gap-3 border-t px-6 py-3.5 md:px-12 ${centered ? "justify-center" : ""}`}
            style={{ borderColor: "var(--line)" }}
          >
            {footer}
          </footer>
        </section>
      </div>
    </div>
  );
}

export function FrameHeading({
  kicker,
  title,
  centered = false,
  children,
}: {
  kicker?: string;
  title: string;
  centered?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`mb-7 max-w-[560px] ${centered ? "text-center" : ""}`}>
      {kicker && (
        <div className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>
          {kicker}
        </div>
      )}
      <h1 className="m-0 text-[26px] font-semibold leading-tight tracking-tight" style={{ color: "var(--ink)" }}>
        {title}
      </h1>
      {children && (
        <p className="mb-0 mt-2 text-[14px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {children}
        </p>
      )}
    </div>
  );
}
