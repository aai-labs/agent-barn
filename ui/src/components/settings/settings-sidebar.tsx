"use client";

import type { ReactNode } from "react";

export type SettingsSidebarItem = {
  key: string;
  label: string;
  icon: ReactNode;
};

/**
 * The left rail of a settings surface. Vertical and sticky beside the content on
 * desktop; a horizontally scrolling row of pills on narrow screens, where a sticky
 * column would eat the viewport.
 *
 * The `lg:w-56` here must stay equal to the `14rem` grid track in SettingsPageLayout.
 */
export function SettingsSidebar({
  eyebrow,
  items,
  activeKey,
  onSelect,
}: {
  eyebrow: string;
  items: SettingsSidebarItem[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  return (
    <aside className="w-full flex-shrink-0 lg:sticky lg:top-[77px] lg:w-56">
      <div
        className="mb-3 px-3 text-[0.7rem] font-semibold uppercase tracking-[0.1em]"
        style={{ color: "var(--ink-4)" }}
      >
        {eyebrow}
      </div>
      <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {items.map((item) => {
          const isActive = activeKey === item.key;
          return (
            <button
              key={item.key}
              type="button"
              className="flex min-w-max items-center gap-2 rounded-lg px-3 py-2 text-left text-[0.82rem] font-medium transition-colors lg:w-full"
              style={{
                background: isActive ? "var(--bg-soft)" : "transparent",
                color: isActive ? "var(--ink)" : "var(--ink-3)",
                fontWeight: isActive ? 600 : 500,
              }}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSelect(item.key)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
