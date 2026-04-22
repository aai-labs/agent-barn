"use client";

import * as React from "react";
import { Building2, LayoutDashboard, Settings } from "lucide-react";
import Link from "next/link";

import { NavMain } from "@/components/nav-main";
import { NavUser } from "@/components/nav-user";
import { OrganizationSwitcher } from "@/components/org-switcher";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "@/components/ui/sidebar";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { useOrganizationContext } from "@/organizations/providers/organization-provider";

const navMain = [
  {
    title: "Dashboard",
    url: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "Settings",
    url: "/dashboard",
    icon: Settings,
  },
];

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { user } = useCurrentUser();
  const { organizations, selectedOrganization, setOrganization } =
    useOrganizationContext();

  const mappedOrganizations = organizations.map((organization) => ({
    id: organization.id,
    name: organization.name,
    logo: Building2,
    isDefault: organization.isDefault,
  }));

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <OrganizationSwitcher
          organizations={mappedOrganizations}
          selectedOrganizationId={selectedOrganization?.id ?? null}
          onOrganizationSelect={(organizationId) => {
            const organization = organizations.find(
              (item) => item.id === organizationId,
            );
            if (organization) {
              setOrganization(organization);
            }
          }}
        />
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
