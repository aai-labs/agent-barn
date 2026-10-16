/** A tile for a provider: its first letter until a brand mark is added for its key. */
export function SyncProviderIcon({ displayName }: { displayName: string }) {
  return (
    <span
      aria-hidden
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border text-[0.9rem] font-semibold"
      style={{ borderColor: "var(--line)", color: "var(--ink)", background: "var(--bg)" }}
    >
      {displayName.charAt(0).toUpperCase()}
    </span>
  );
}
