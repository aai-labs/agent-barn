"use client";

import * as React from "react";
import { Building2, ChevronsUpDown, Plus } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { CreateOrganizationDialog } from "@/features/organizations/components/create-organization-dialog";

export function OrganizationSwitcher({
  organizations,
  selectedOrganizationId,
  onOrganizationSelect,
}: {
  organizations: {
    id: string;
    name: string;
    logo?: React.ElementType;
    isDefault?: boolean;
  }[];
  selectedOrganizationId: string | null;
  onOrganizationSelect: (organizationId: string) => void;
}) {
  const { isMobile } = useSidebar();
  const [isCreateDialogOpen, setIsCreateDialogOpen] = React.useState(false);

  const activeOrganization = React.useMemo(
    () =>
      organizations.find((org) => org.id === selectedOrganizationId) ??
      organizations[0],
    [organizations, selectedOrganizationId],
  );

  if (!activeOrganization) {
    return null;
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <CreateOrganizationDialog
          open={isCreateDialogOpen}
          onOpenChange={setIsCreateDialogOpen}
          onCreated={onOrganizationSelect}
        />
        <DropdownMenu>
          <DropdownMenuTrigger className="w-full">
            <SidebarMenuButton
              asChild
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <div>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  {activeOrganization.logo ? (
                    <activeOrganization.logo className="size-4" />
                  ) : (
                    <Building2 className="size-4" />
                  )}
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">
                    {activeOrganization.name}
                  </span>
                  <span className="truncate text-xs">
                    {activeOrganization.isDefault ? "Default" : "Organization"}
                  </span>
                </div>
                <ChevronsUpDown className="ml-auto" />
              </div>
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            align="start"
            side={isMobile ? "bottom" : "right"}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              organizations
            </DropdownMenuLabel>
            {organizations.map((organization, index) => (
              <DropdownMenuItem
                key={organization.id}
                onClick={() => onOrganizationSelect(organization.id)}
                className="gap-2 p-2"
              >
                <div className="flex size-6 items-center justify-center rounded-md border">
                  {organization.logo ? (
                    <organization.logo className="size-3.5 shrink-0" />
                  ) : (
                    <Building2 className="size-3.5 shrink-0" />
                  )}
                </div>
                {organization.name}
                <DropdownMenuShortcut>⌘{index + 1}</DropdownMenuShortcut>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="gap-2 p-2"
              onClick={() => setIsCreateDialogOpen(true)}
            >
              <div className="flex size-6 items-center justify-center rounded-md border">
                <Plus className="size-3.5 shrink-0" />
              </div>
              Add organization
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
