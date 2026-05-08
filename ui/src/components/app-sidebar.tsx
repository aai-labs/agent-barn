"use client";

import * as React from "react";
import { Building, LayoutDashboard, Users } from "lucide-react";
import Link from "next/link";

import { NavMain } from "@/components/nav-main";
import { NavUser } from "@/components/nav-user";
import { SuperAdminOrganizationBadge } from "@/components/super-admin-organization-badge";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "@/components/ui/sidebar";
import { useCurrentUser } from "@/auth/providers/user-context-provider";

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { user } = useCurrentUser();
  const navMain = [
    {
      title: "Dashboard",
      url: "/dashboard",
      icon: LayoutDashboard,
    },
    ...(user.isSuperuser
      ? [
          {
            title: "Users",
            url: "/dashboard/users",
            icon: Users,
          },
          {
            title: "Organizations",
            url: "/dashboard/organizations",
            icon: Building,
          },
        ]
      : []),
  ];

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SuperAdminOrganizationBadge />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={navMain} LinkComponent={Link} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser
          user={{
            name: user.fullName ?? user.email,
            email: user.email,
            avatar: "",
          }}
        />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
