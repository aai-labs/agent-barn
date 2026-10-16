import { syncProviderIcon } from "@/components/brand-icons";

/** A tile for a provider: its brand mark, or its first letter when it has none. */
export function SyncProviderIcon({ providerKey, displayName }: { providerKey: string; displayName: string }) {
  const mark = syncProviderIcon(providerKey, { size: 22 });
  return (
    <span
      aria-hidden={mark ? undefined : true}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border text-[0.9rem] font-semibold"
      style={{ borderColor: "var(--line)", color: "var(--ink)", background: "var(--bg)" }}
    >
      {mark ?? displayName.charAt(0).toUpperCase()}
    </span>
  );
}
