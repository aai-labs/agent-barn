"use client";

import { useState } from "react";
import { KeyRound, Loader2, PlusIcon, Shield, Trash2, UserRound } from "lucide-react";

import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { AppErrorState } from "@/components/app-error-state";
import { ListPageHeader } from "@/components/list-page-header";

import { useInfiniteUsers } from "../hooks/use-infinite-users";
import type { UserRead } from "../schemas";

import { CreateUserDialog } from "./create-user-dialog";
import { DeleteUserDialog } from "./delete-user-dialog";
import { ResetPasswordDialog } from "./reset-password-dialog";

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
  const [deleteTarget, setDeleteTarget] = useState<UserRead | null>(null);
  const [resetTarget, setResetTarget] = useState<UserRead | null>(null);
  const { user: currentUser } = useCurrentUser();

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
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
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
            <PlusIcon width={15} height={15} /> Create user
          </button>
        }
      />

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
            <div key={user.id} className="af-card af-card-hover px-5 py-[18px] relative">
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
              <div className="text-[12.5px] mb-3.5" style={{ color: "var(--ink-3)" }}>
                Created: {formatDate(user.createdAt)}
              </div>
              <div
                className="text-[12px] pt-3"
                style={{ borderTop: "1px solid var(--line)", color: "var(--ink-4)" }}
              >
                Email verified: {formatDate(user.emailVerifiedAt)}
              </div>

              {user.id !== currentUser.id && (
                <div className="absolute top-3 right-3 flex items-center gap-0.5">
                  <button
                    className="p-1.5 rounded-lg transition-colors"
                    style={{ color: "var(--ink-4)" }}
                    onClick={() => setResetTarget(user)}
                    title="Reset password"
                    aria-label="Reset password"
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--ink)"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--ink-4)"; }}
                  >
                    <KeyRound width={14} height={14} />
                  </button>
                  <button
                    className="p-1.5 rounded-lg transition-colors"
                    style={{ color: "var(--ink-4)" }}
                    onClick={() => setDeleteTarget(user)}
                    title="Delete user"
                    aria-label="Delete user"
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--err)"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--ink-4)"; }}
                  >
                    <Trash2 width={14} height={14} />
                  </button>
                </div>
              )}
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

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <DeleteUserDialog
        user={deleteTarget}
        open={deleteTarget !== null}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
      />
      <ResetPasswordDialog
        user={resetTarget}
        open={resetTarget !== null}
        onOpenChange={(v) => { if (!v) setResetTarget(null); }}
      />
    </div>
  );
}
