"use client";

import { RouteErrorState } from "@/components/route-error-state";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-svh">
        <RouteErrorState
          error={error}
          reset={reset}
          title="We couldn't load this page"
          description="A page-level request failed before the app could finish rendering."
          className="min-h-svh"
        />
      </body>
    </html>
  );
}
