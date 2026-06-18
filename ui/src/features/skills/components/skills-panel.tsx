"use client";

import { useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { PlusIcon, ShieldIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { type Skill, type SkillSource } from "../schemas";
import { useSkills } from "../hooks/use-skills";
import { SKILL_PROVIDER_LABELS } from "../utils";
import { SkillDrawer, SkillSourceBadge } from "./skill-drawer";

const SOURCE_FILTERS: Array<{ value: SkillSource | ""; label: string }> = [
  { value: "", label: "All sources" },
  { value: "aai_cli", label: "Platform" },
  { value: "custom", label: "Custom" },
];

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; skill: Skill };

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-start gap-2 text-[13px] rounded-xl px-3.5 py-3 mb-5 leading-[1.5]"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
    >
      {SKILL_PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-xs font-semibold uppercase tracking-[0.07em] pt-4 pb-1"
      style={{ color: "var(--ink-4)" }}
    >
      {children}
    </div>
  );
}


export function SkillsPanel() {
  const { skills, isLoading, error, refetch } = useSkills();
  const [drawer, setDrawer] = useState<DrawerMode | null>(null);
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SkillSource | "">("");

  const filtered = skills.filter((s) => {
    const matchesSearch = !search || s.name.toLowerCase().includes(search.toLowerCase());
    const matchesSource = !sourceFilter || s.source === sourceFilter;
    return matchesSearch && matchesSource;
  });

  const platformSkills = filtered.filter((s) => s.source === "aai_cli");
  const customSkills = filtered.filter((s) => s.source === "custom");

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 animate-pulse">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-11 rounded-xl" style={{ background: "var(--bg-soft)" }} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load skills"
        description="The skills list is unavailable right now."
        onRetry={() => {
          void refetch();
        }}
        retryLabel="Retry"
      />
    );
  }

  return (
    <>
      <Hint>
        <ShieldIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Platform skills are provided by AAI Labs and cannot be modified. Custom skills are uploaded
        by your organization and can be assigned to agents.
      </Hint>

      <div className="mb-4 flex items-center gap-2.5">
        <div className="relative flex-1">
          <input
            className="af-input w-full"
            placeholder="Search skills…"
            aria-label="Search skills"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="af-input w-full flex items-center gap-2 whitespace-nowrap"
                aria-label="Filter by source"
              >
                {SOURCE_FILTERS.find((f) => f.value === sourceFilter)?.label ?? "All sources"}
                <ChevronDownIcon size={13} className="opacity-50 flex-shrink-0" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuRadioGroup
                value={sourceFilter}
                onValueChange={(v) => setSourceFilter(v as SkillSource | "")}
              >
                {SOURCE_FILTERS.map((f) => (
                  <DropdownMenuRadioItem key={f.value} value={f.value}>
                    {f.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <button
          className="af-btn af-btn-primary ml-auto"
          onClick={() => setDrawer({ kind: "create" })}
        >
          <PlusIcon /> New skill
        </button>
      </div>

      {filtered.length === 0 && skills.length > 0 && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          No skills match.
        </div>
      )}

      {platformSkills.length > 0 && (
        <div>
          <SectionHeader>Platform</SectionHeader>
          {platformSkills.map((skill) => (
            <div
              key={skill.id}
              className="flex items-center gap-3 px-0 py-3.5"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div className="flex-1 min-w-0">
                <div
                  className="font-medium text-[14px] flex items-center gap-2"
                  style={{ color: "var(--ink)" }}
                >
                  <span>{skill.name}</span>
                  <SkillSourceBadge source={skill.source} />
                </div>
                {skill.requiredProviders.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {skill.requiredProviders.map((p) => (
                      <ProviderBadge key={p} provider={p} />
                    ))}
                  </div>
                )}
              </div>
              <button
                className="af-btn af-btn-sm af-btn-ghost"
                onClick={() => setDrawer({ kind: "view", skill })}
              >
                View
              </button>
            </div>
          ))}
        </div>
      )}

      {customSkills.length > 0 && (
        <div>
          <SectionHeader>Custom</SectionHeader>
          {customSkills.map((skill) => (
            <div
              key={skill.id}
              className="flex items-center gap-3 px-0 py-3.5"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div className="flex-1 min-w-0">
                <div
                  className="font-medium text-[14px] flex items-center gap-2"
                  style={{ color: "var(--ink)" }}
                >
                  <span>{skill.name}</span>
                  <SkillSourceBadge source={skill.source} />
                </div>
                {skill.requiredProviders.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {skill.requiredProviders.map((p) => (
                      <ProviderBadge key={p} provider={p} />
                    ))}
                  </div>
                )}
              </div>
              <button
                className="af-btn af-btn-sm af-btn-ghost"
                onClick={() => setDrawer({ kind: "view", skill })}
              >
                View
              </button>
            </div>
          ))}
        </div>
      )}

      {skills.length === 0 && (
        <div
          className="flex flex-col items-center justify-center text-center py-10 rounded-2xl"
          style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
        >
          <div className="font-medium text-[0.9375rem] mb-1" style={{ color: "var(--ink)" }}>
            No skills yet
          </div>
          <div className="text-[0.844rem]">Create your first custom skill to get started.</div>
        </div>
      )}

      {drawer && <SkillDrawer mode={drawer} onClose={() => setDrawer(null)} />}
    </>
  );
}