"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Building2,
  CalendarDays,
  ChevronLeft,
  Loader2,
  MailPlusIcon,
  ShieldCheck,
  ShieldOff,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import { DetailStatTile } from "@/components/detail-stat-tile";
import { Button } from "@/components/ui/button";

import { useResendUserInvite } from "../hooks/use-create-user";
import { usePlatformUser } from "../hooks/use-platform-user";
import { PlatformPrivilegeDialog } from "./platform-privilege-dialog";
import { UserInviteLinkDialog } from "./user-invite-link-dialog";

function formatDateTime(date: string | null | undefined) {
  if (!date) return null;
  return new Date(date).toLocaleString();
}

const ROLE_LABEL: Record<string, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MEMBER: "Member",
};

export function UserDetail({ userId }: { userId: string }) {
  const { user: currentUser } = useCurrentUser();
  const { user, isLoading, error, refetch } = usePlatformUser(userId);
  const resendInvite = useResendUserInvite();

  const [privilegeOpen, setPrivilegeOpen] = useState(false);
  const [resentInvite, setResentInvite] = useState<{
    email: string;
    inviteLink: string;
  } | null>(null);

  if (isLoading) {
    return (
      <div className="af-page">
        <div
          className="flex items-center gap-2 py-10 text-[13.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          <Loader2 width={15} height={15} className="animate-spin" /> Loading user…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="af-page">
        <AppErrorState
          error={error}
          title="We couldn't load this user"
          description="The user detail is unavailable right now."
          onRetry={() => { void refetch(); }}
          retryLabel="Retry"
          className="min-h-[240px] p-0"
        />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="af-page">
        <div className="text-[14px]" style={{ color: "var(--ink-3)" }}>User not found.</div>
      </div>
    );
  }

  const isSelf = user.id === currentUser.id;
  const memberships = user.organizationUsers ?? [];

  return (
    <div className="af-page">
      <Link
        href="/dashboard/platform/users"
        className="inline-flex items-center gap-1 text-[13px] mb-4"
        style={{ color: "var(--ink-3)" }}
      >
        <ChevronLeft width={14} height={14} /> Users
      </Link>

      <div className="flex items-start gap-4 mb-7">
        <div
          className="grid h-14 w-14 flex-shrink-0 place-items-center rounded-2xl text-white"
          style={{ background: "linear-gradient(135deg, #4338ca, #7c3aed)" }}
          aria-hidden
        >
          <UserRound width={22} height={22} />
        </div>

        <div className="min-w-0 flex-1 pt-0.5">
          <h1
            className="m-0 truncate text-[26px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            {user.fullName || (user.isPlatformAdmin ? "Super User" : "Unnamed user")}
          </h1>
          <p className="m-0 mt-1 text-[14px]" style={{ color: "var(--ink-3)" }}>
            {user.email}
          </p>
        </div>

        {!isSelf && (
          <div className="flex flex-shrink-0 items-center gap-2">
            {!user.emailVerifiedAt && (
              <Button
                type="button"
                variant="outline"
                disabled={resendInvite.isPending}
                onClick={() => {
                  resendInvite.mutate(user.id, {
                    onSuccess: (result) => {
                      setResentInvite({ email: user.email, inviteLink: result.inviteLink });
                    },
                    onError: (err) => {
                      toast.error(err.message || "Failed to resend invitation");
                    },
                  });
                }}
              >
                {resendInvite.isPending ? (
                  <Loader2 data-icon="inline-start" className="animate-spin" />
                ) : (
                  <MailPlusIcon data-icon="inline-start" />
                )}
                Resend invitation
              </Button>
            )}
            <Button
              type="button"
              variant={user.isPlatformAdmin ? "outline" : "default"}
              onClick={() => setPrivilegeOpen(true)}
            >
              {user.isPlatformAdmin ? (
                <ShieldOff data-icon="inline-start" />
              ) : (
                <ShieldCheck data-icon="inline-start" />
              )}
              {user.isPlatformAdmin ? "Revoke Platform Admin" : "Grant Platform Admin"}
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3 mb-9">
        <DetailStatTile
          icon={user.isPlatformAdmin ? <ShieldCheck width={14} height={14} /> : <ShieldOff width={14} height={14} />}
          label="Platform privilege"
        >
          {user.isPlatformAdmin ? "Platform admin" : "Standard user"}
        </DetailStatTile>
        <DetailStatTile icon={<MailPlusIcon width={14} height={14} />} label="Email verified">
          {formatDateTime(user.emailVerifiedAt) ?? "Not verified"}
        </DetailStatTile>
        <DetailStatTile icon={<CalendarDays width={14} height={14} />} label="Created">
          {new Date(user.createdAt).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </DetailStatTile>
      </div>

      <div style={{ borderTop: "1px solid var(--line)" }} className="pt-8">
        <h2 className="text-[16px] font-semibold m-0 mb-0.5" style={{ color: "var(--ink)" }}>
          Organizations
        </h2>
        <p className="text-[13px] m-0 mb-4" style={{ color: "var(--ink-4)" }}>
          {memberships.length} {memberships.length === 1 ? "organization" : "organizations"}
        </p>

        {memberships.length === 0 ? (
          <div
            className="flex items-center justify-center text-center py-10 rounded-2xl text-[13.5px]"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
          >
            Not a member of any organization.
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {memberships.map((membership) => (
              <Link
                key={membership.id}
                href={`/dashboard/platform/organizations/${membership.organizationId}`}
                className="af-card af-card-hover flex items-center gap-4 px-5 py-3.5"
              >
                <Building2 width={16} height={16} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-[14px] truncate" style={{ color: "var(--ink)" }}>
                    {membership.organization.name}
                  </div>
                  <div className="text-[12.5px] truncate" style={{ color: "var(--ink-3)" }}>
                    {membership.organization.description || "No description"}
                  </div>
                </div>
                <span
                  className="flex-shrink-0 rounded-full px-2.5 py-1 text-[12px] font-medium"
                  style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                >
                  {ROLE_LABEL[membership.role] ?? membership.role}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      <PlatformPrivilegeDialog
        user={user}
        open={privilegeOpen}
        onOpenChange={setPrivilegeOpen}
      />
      <UserInviteLinkDialog
        email={resentInvite?.email ?? ""}
        inviteLink={resentInvite?.inviteLink ?? ""}
        open={resentInvite !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setResentInvite(null);
        }}
      />
    </div>
  );
}
