"use client";

import type { ComponentType, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

export function NavMain({
  items,
  LinkComponent,
}: {
  items: {
    title: string;
    url: string;
    icon?: LucideIcon;
  }[];
  LinkComponent?: ComponentType<{ href: string; children: ReactNode }>;
}) {
  return (
    <SidebarGroup>
      <SidebarGroupLabel>Platform</SidebarGroupLabel>
      <SidebarMenu>
        {items.map((item) => (
          <SidebarMenuItem key={item.title}>
            {LinkComponent ? (
              <SidebarMenuButton asChild tooltip={item.title}>
                <LinkComponent href={item.url}>
                  {item.icon && <item.icon />}
                  <span>{item.title}</span>
                </LinkComponent>
              </SidebarMenuButton>
            ) : (
              <SidebarMenuButton tooltip={item.title}>
                {item.icon && <item.icon />}
                <span>{item.title}</span>
              </SidebarMenuButton>
            )}
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
