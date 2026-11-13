import { cn } from "@/lib/utils";

export function BotTrustNotice({ className }: { className?: string }) {
  return (
    <p className={cn("m-0 text-[12.5px] leading-relaxed", className)} style={{ color: "var(--warn)" }}>
      Bots in one Agent can read each other&apos;s credentials. Bots that need separate access must be separate Agents.
    </p>
  );
}
