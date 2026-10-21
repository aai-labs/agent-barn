"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, User } from "lucide-react";

import { useLogout } from "@/auth/hooks/use-logout";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { USER_AVATAR_BACKGROUND, userInitials } from "../utils";

/**
 * The signed-in person's menu at the end of the path bar: their account and logging
 * out. Platform View is reached from the context switcher, so it is not repeated here.
 */
export function UserMenu() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { logout, isLoggingOut } = useLogout();

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          title={user.fullName ?? user.email}
          className="grid h-8 w-8 place-items-center rounded-full text-[11.5px] font-semibold text-white"
          style={{ background: USER_AVATAR_BACKGROUND }}
        >
          {userInitials(user)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" sideOffset={8} className="w-64">
        <DropdownMenuLabel className="font-normal">
          <div className="truncate text-[13.5px] font-medium" style={{ color: "var(--ink)" }}>
            {user.fullName ?? user.email}
          </div>
          <div className="truncate text-[12px]" style={{ color: "var(--ink-4)" }}>
            {user.email}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/dashboard/account">
            <User aria-hidden /> Account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={isLoggingOut}
          onSelect={async () => {
            await logout();
            router.push("/login");
          }}
        >
          <LogOut aria-hidden /> {isLoggingOut ? "Logging out…" : "Log out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
