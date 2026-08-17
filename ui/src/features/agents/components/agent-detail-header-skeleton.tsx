export function AgentDetailHeaderSkeleton() {
  return (
    <div className="flex items-center gap-5.5 pb-8 animate-pulse">
      <div className="h-18 w-18 flex-shrink-0 rounded-full" style={{ background: "var(--bg-soft)" }} />
      <div className="flex flex-1 flex-col gap-2">
        <div className="h-9 w-48 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-32 rounded-md" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-20 rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>
    </div>
  );
}
