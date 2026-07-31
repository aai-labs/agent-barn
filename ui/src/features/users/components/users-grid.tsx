"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Loader2,
  MailPlusIcon,
  Shield,
  ShieldCheck,
  ShieldOff,
  UserPlusIcon,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import { ListPageHeader } from "@/components/list-page-header";
import { Button } from "@/components/ui/button";

import { useResendUserInvite } from "../hooks/use-create-user";
import { useInfiniteUsers } from "../hooks/use-infinite-users";
import type { UserRead } from "../schemas";

import { CreateUserDialog } from "./create-user-dialog";
import { PlatformPrivilegeDialog } from "./platform-privilege-dialog";
import { UserInviteLinkDialog } from "./user-invite-link-dialog";

function formatDate(date: string | null | undefined) {
  if (!date) return "Not verified";
  return new Date(date).toLocaleString();
}

function LoadingCard() {
  return (
    <div className="af-card px-5 py-[18px] animate-pulse">
      <div className="h-[15px] w-36 rounded-md mb-1.5" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-52 rounded-md mb-4" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-28 rounded-md mb-2" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[13px] w-40 rounded-md mb-5" style={{ background: "var(--bg-soft)" }} />
      <div className="h-[12px] w-44 rounded-md" style={{ background: "var(--bg-soft)" }} />
    </div>
  );
}

export function UsersGrid() {
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [privilegeTarget, setPrivilegeTarget] = useState<UserRead | null>(null);
  const [resentInvite, setResentInvite] = useState<{
    email: string;
    inviteLink: string;
  } | null>(null);
  const { user: currentUser } = useCurrentUser();
  const resendInvite = useResendUserInvite();

  const {
    users,
    total,
    hasNextPage,
    fetchNextPage,
    error,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useInfiniteUsers({ search });

  return (
    <div className="af-page">
      <ListPageHeader
        title="Users"
        description="Platform view of all users."
        count={total}
        noun="user"
        onSearch={setSearch}
        searchPlaceholder="Search by name or email"
        action={
          <button
            className="af-btn af-btn-primary flex-shrink-0"
            onClick={() => setCreateOpen(true)}
          >
            <UserPlusIcon width={15} height={15} /> Create user
          </button>
        }
      />

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />

      {isLoading ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          {Array.from({ length: 6 }).map((_, i) => <LoadingCard key={i} />)}
        </div>
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load users"
          description="The users list is unavailable right now."
          onRetry={() => { void refetch(); }}
          retryLabel="Retry users"
          className="min-h-[240px] p-0"
        />
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
          {users.map((user) => (
            <div key={user.id} className="af-card h-full flex flex-col overflow-hidden">
              <Link
                href={`/dashboard/platform/users/${user.id}`}
                className="flex-1 block px-5 pt-[18px] pb-4 transition-colors hover:bg-[var(--bg-soft)]"
              >
                <div className="flex items-center gap-2 mb-1">
                  <UserRound width={14} height={14} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                  <span className="font-semibold text-[14.5px] truncate" style={{ color: "var(--ink)" }}>
                    {user.fullName || (user.isPlatformAdmin ? "Super User" : "Unnamed user")}
                  </span>
                </div>
                <div className="text-[13px] mb-4 truncate" style={{ color: "var(--ink-3)" }}>
                  {user.email}
                </div>
                <div className="flex items-center gap-1.5 text-[12.5px] mb-1.5" style={{ color: "var(--ink-3)" }}>
                  <Shield width={12} height={12} style={{ flexShrink: 0 }} />
                  {user.isPlatformAdmin ? "Platform admin" : "User"}
                </div>
                <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  Created: {formatDate(user.createdAt)}
                </div>
              </Link>

              <div
                className="flex items-center gap-2 flex-wrap px-5 py-3 mt-auto"
                style={{ borderTop: "1px solid var(--line)" }}
              >
                {!user.emailVerifiedAt && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={resendInvite.isPending}
                    onClick={() => {
                      resendInvite.mutate(user.id, {
                        onSuccess: (result) => {
                          setResentInvite({
                            email: user.email,
                            inviteLink: result.inviteLink,
                          });
                        },
                        onError: (error) => {
                          toast.error(error.message || "Failed to resend invitation");
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

                {user.id !== currentUser.id && (
                  <Button
                    type="button"
                    variant={user.isPlatformAdmin ? "outline" : "secondary"}
                    size="sm"
                    onClick={() => setPrivilegeTarget(user)}
                  >
                    {user.isPlatformAdmin ? (
                      <ShieldOff data-icon="inline-start" />
                    ) : (
                      <ShieldCheck data-icon="inline-start" />
                    )}
                    {user.isPlatformAdmin ? "Revoke Platform Admin" : "Grant Platform Admin"}
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && users.length === 0 && (
        <div
          className="flex flex-col items-center justify-center text-center py-16 rounded-2xl"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <div className="font-medium text-[15px] mb-1" style={{ color: "var(--ink)" }}>No users found</div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>Try a different search term.</div>
        </div>
      )}

      {hasNextPage && (
        <div className="flex justify-center mt-6">
          <button className="af-btn" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage
              ? <><Loader2 width={14} height={14} className="animate-spin" /> Loading more</>
              : "Load more users"}
          </button>
        </div>
      )}

      <PlatformPrivilegeDialog
        user={privilegeTarget}
        open={privilegeTarget !== null}
        onOpenChange={(v) => { if (!v) setPrivilegeTarget(null); }}
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
