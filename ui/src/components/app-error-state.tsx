"use client";

import { cn } from "@/lib/utils";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import { AlertCircleIcon } from "@/components/icons";

type AppErrorStateProps = {
  error?: unknown;
  title?: string;
  description?: string;
  retryLabel?: string;
  onRetry?: () => void;
  className?: string;
};

export function AppErrorState({
  error,
  title,
  description,
  retryLabel = "Try again",
  onRetry,
  className,
}: AppErrorStateProps) {
  const display = getErrorDisplay(error, {
    title: title ?? "Something went wrong",
    description: description ?? "Please try again in a moment.",
  });

  const errorMessage = error instanceof Error ? error.message : display.description;

  return (
    <div
      className={cn(
        "flex min-h-[320px] items-center justify-center p-4 md:p-6",
        className,
      )}
    >
      <div className="af-card w-full max-w-xl px-6 py-6">
        <div className="font-semibold text-[16px] mb-1" style={{ color: "var(--ink)" }}>
          {title ?? display.title}
        </div>
        <div className="text-[13.5px] mb-5" style={{ color: "var(--ink-3)" }}>
          {description ?? display.description}
        </div>

        <div
          className="flex items-start gap-3 rounded-xl px-4 py-3.5 mb-5"
          style={{ background: "var(--err-soft)", border: "1px solid var(--err)", borderColor: "color-mix(in srgb, var(--err) 30%, transparent)" }}
        >
          <AlertCircleIcon size={15} style={{ color: "var(--err)", flexShrink: 0, marginTop: 1 }} />
          <div>
            <div className="font-medium text-[13px] mb-0.5" style={{ color: "var(--err)" }}>
              Request failed
            </div>
            <div className="text-[12.5px] leading-[1.5]" style={{ color: "var(--err)" }}>
              {errorMessage}
            </div>
          </div>
        </div>

        {onRetry && (
          <button className="af-btn" onClick={onRetry}>
            {retryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
