"use client";

import { useRouter } from "next/navigation";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useLogout } from "@/auth/hooks/use-logout";
import { LogoMark } from "@/components/logo-mark";

/** Someone signed in who belongs to no organization: nothing to show, so say why. */
export function NoOrganization() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { logout, isLoggingOut } = useLogout();
  // Signed themselves up, and no administrator ended the trial: they deleted it.
  const trialForfeited = Boolean(user.signedUpAt) && !user.trialEndedAt;

  return (
    <div className="flex min-h-svh items-center justify-center p-6" style={{ background: "var(--bg)" }}>
      <section
        className="w-full max-w-md rounded-2xl px-8 py-9 text-center"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
      >
        <div className="mb-4 flex justify-center">
          <LogoMark size={36} />
        </div>
        <h1 className="m-0 mb-2 text-[22px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
          You&apos;re not in an organization
        </h1>
        <p className="m-0 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {trialForfeited
            ? "Your free trial has ended because its organization was deleted. Ask someone to invite you to their organization to keep using Agent Barn."
            : "Ask someone to invite you to their organization. Once they do, it appears here."}
        </p>
        <p className="mb-0 mt-3 text-[12.5px]" style={{ color: "var(--ink-4)" }}>
          Signed in as {user.email}
        </p>
        <button
          type="button"
          className="af-btn af-btn-lg mt-6"
          disabled={isLoggingOut}
          onClick={() => void logout().then(() => router.replace("/login"))}
        >
          Sign out
        </button>
      </section>
    </div>
  );
}
