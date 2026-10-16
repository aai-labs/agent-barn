"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Ellipsis, LogOut, User } from "lucide-react";

import { useLogout } from "@/auth/hooks/use-logout";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import {
  NAV_VARIANTS,
  NAV_VARIANT_LABELS,
  useNavVariant,
  type NavVariant,
} from "../providers/nav-variant-provider";
import { USER_AVATAR_BACKGROUND, userInitials } from "../utils";

/**
 * The signed-in person's menu at the foot of the navigation: their account, the
 * navigation preview switch, and logging out. Platform View is reached from the
 * context switcher, so it is not repeated here. An avatar on the rail or at the end of
 * D2's top bar; a row naming the person in C's sidebar.
 */
export function UserMenu({
  appearance = "avatar",
  placement = "side",
}: {
  appearance?: "avatar" | "row";
  /** `below` opens the menu downward, for the avatar at the end of D2's top bar. */
  placement?: "side" | "below";
}) {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { logout, isLoggingOut } = useLogout();
  const { variant, setVariant } = useNavVariant();

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        {appearance === "row" ? (
          <button
            type="button"
            aria-label="Account menu"
            className="af-hover-bg flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left"
          >
            <span
              className="grid h-[30px] w-[30px] flex-shrink-0 place-items-center rounded-full text-[11.5px] font-semibold text-white"
              style={{ background: USER_AVATAR_BACKGROUND }}
            >
              {userInitials(user)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium" style={{ color: "var(--ink)" }}>
                {user.fullName ?? user.email}
              </span>
              <span className="block truncate text-[11.5px]" style={{ color: "var(--ink-4)" }}>
                {user.email}
              </span>
            </span>
            <Ellipsis size={16} aria-hidden style={{ color: "var(--ink-3)" }} />
          </button>
        ) : (
          <button
            type="button"
            aria-label="Account menu"
            title={user.fullName ?? user.email}
            className="grid h-8 w-8 place-items-center rounded-full text-[11.5px] font-semibold text-white"
            style={{ background: USER_AVATAR_BACKGROUND }}
          >
            {userInitials(user)}
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={placement === "below" ? "bottom" : appearance === "row" ? "top" : "right"}
        align={appearance === "row" ? "start" : "end"}
        sideOffset={placement === "below" ? 8 : appearance === "row" ? 6 : 12}
        className="w-64"
      >
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
        <DropdownMenuLabel className="text-[11px] uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
          Navigation preview
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={variant} onValueChange={(value) => setVariant(value as NavVariant)}>
          {NAV_VARIANTS.map((option) => (
            <DropdownMenuRadioItem key={option} value={option}>
              {NAV_VARIANT_LABELS[option]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
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
