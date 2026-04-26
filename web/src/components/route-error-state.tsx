"use client";

import { AppErrorState } from "@/components/app-error-state";

type RouteErrorStateProps = {
  error: Error & { digest?: string };
  reset: () => void;
  title?: string;
  description?: string;
  className?: string;
};

export function RouteErrorState({
  error,
  reset,
  title,
  description,
  className,
}: RouteErrorStateProps) {
  return (
    <AppErrorState
      error={error}
      title={title ?? "We couldn't load this page"}
      description={
        description ??
        "A page-level request failed. Try again and we'll reload the route."
      }
      className={className}
      onRetry={reset}
      retryLabel="Reload page"
    />
  );
}
