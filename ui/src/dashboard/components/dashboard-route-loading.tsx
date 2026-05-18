function LoadingCard() {
  return (
    <div className="af-card px-5 py-[18px] animate-pulse">
      <div className="h-[15px] w-40 rounded-md mb-1.5" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-56 rounded-md mb-4" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-full rounded-md mb-2" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-5/6 rounded-md" style={{ background: "var(--bg-soft)" }} />
    </div>
  );
}

export function DashboardRouteLoading({
  title = "Loading dashboard",
  description = "Preparing your workspace.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="animate-pulse mb-8">
        <div className="h-7 w-52 rounded-md mb-2" style={{ background: "var(--bg-soft)" }} />
        <div className="h-4 w-80 max-w-full rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>

      <div className="sr-only" aria-live="polite">
        {title}. {description}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <LoadingCard />
        <LoadingCard />
      </div>
    </div>
  );
}
