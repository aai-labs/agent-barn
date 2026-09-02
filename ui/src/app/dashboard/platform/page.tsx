import Link from "next/link";
import { BuildingIcon, ServerIcon, UsersIcon } from "@/components/icons";
import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformStatsPanel } from "@/features/platform-stats/components/platform-stats-panel";
import { FileText, Sparkles } from "lucide-react";

const platformLinks = [
  {
    href: "/dashboard/platform/users",
    title: "Users",
    description:
      "Manage platform accounts, password resets, and account removal.",
    Icon: UsersIcon,
  },
  {
    href: "/dashboard/platform/organizations",
    title: "Organizations",
    description:
      "Manage customer organizations and jump into organization view.",
    Icon: BuildingIcon,
  },
  {
    href: "/dashboard/platform/event-deliveries",
    title: "Event Deliveries",
    description: "Inspect delivery pipeline health and diagnose handler failures.",
    Icon: ServerIcon,
  },
  {
    href: "/dashboard/platform/templates",
    title: "Platform Templates",
    description: "Author and publish the global agent prompt templates.",
    Icon: FileText,
  },
  {
    href: "/dashboard/platform/skills",
    title: "Platform Skills",
    description: "Manage the global Skill catalogue, including the bundled aai-cli integrations.",
    Icon: Sparkles,
  },
];

export default function PlatformPage() {
  return (
    <PlatformAdminOnly>
      <div className="af-page">
        <div className="mb-8">
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            Platform
          </h1>
          <p className="mt-2 text-[14.5px]" style={{ color: "var(--ink-3)" }}>
            Product-wide administration outside any active organization.
          </p>
        </div>

        <div
          className="grid gap-4 mb-10"
          style={{
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          }}
        >
          {platformLinks.map(({ href, title, description, Icon }) => (
            <Link
              key={href}
              href={href}
              className="af-card af-card-hover block px-5 py-[18px]"
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon size={15} style={{ color: "var(--ink-4)" }} />
                <span
                  className="font-semibold text-[15px]"
                  style={{ color: "var(--ink)" }}
                >
                  {title}
                </span>
              </div>
              <p
                className="text-[13.5px] leading-[1.45]"
                style={{ color: "var(--ink-3)" }}
              >
                {description}
              </p>
            </Link>
          ))}
        </div>

        <PlatformStatsPanel />
      </div>
    </PlatformAdminOnly>
  );
}
