import Link from "next/link";
import { BuildingIcon, ServerIcon, UsersIcon } from "@/components/icons";
import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";

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
];

export default function PlatformPage() {
  return (
    <PlatformAdminOnly>
      <div className="max-w-[980px] mx-auto px-10 pt-9 pb-24">
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
          className="grid gap-4"
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
      </div>
    </PlatformAdminOnly>
  );
}
