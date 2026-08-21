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
import { Pagination } from "@/features/agents/components/pagination";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { type Skill, type SkillSource } from "../schemas";
import { useSkills } from "../hooks/use-skills";
import { SKILLS_PAGE_SIZE, SKILL_PROVIDER_LABELS } from "../utils";
import { SkillDrawer, SkillSourceBadge } from "./skill-drawer";
import { SettingsHint } from "@/components/settings/settings-hint";

const SOURCE_FILTERS: Array<{ value: SkillSource | ""; label: string }> = [
  { value: "", label: "All sources" },
  { value: "aai_cli", label: "Platform" },
  { value: "custom", label: "Custom" },
];

type DrawerMode =
  | { kind: "create" }
  | { kind: "view"; skill: Skill };

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[0.7rem] font-medium"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
    >
      {SKILL_PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

export function SkillsPanel() {
  const { canManage } = useActiveOrgRole();
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SkillSource | "">("");
  const [page, setPage] = useState(1);
  const [drawer, setDrawer] = useState<DrawerMode | null>(null);

  const { skills, total, isLoading, error, refetch } = useSkills({
    search: search || undefined,
    source: sourceFilter || undefined,
    page,
  });

  const totalPages = Math.max(1, Math.ceil(total / SKILLS_PAGE_SIZE));

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
  }

  function handleSourceChange(value: SkillSource | "") {
    setSourceFilter(value);
    setPage(1);
  }

  return (
    <>
      <SettingsHint>
        <ShieldIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Platform skills are provided by AAI Labs and cannot be modified. Custom skills are uploaded
        by your organization and can be assigned to agents.
      </SettingsHint>

      <div className="af-card p-5">
        <div className="mb-4 flex items-center gap-2.5">
          <div className="relative flex-1">
            <input
              className="af-input w-full"
              placeholder="Search skills…"
              aria-label="Search skills"
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
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
                  onValueChange={(v) => handleSourceChange(v as SkillSource | "")}
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
          {canManage && (
            <button
              className="af-btn af-btn-primary ml-auto"
              onClick={() => setDrawer({ kind: "create" })}
            >
              <PlusIcon /> New skill
            </button>
          )}
        </div>

        {isLoading && (
          <div className="py-8 text-center text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            Loading skills…
          </div>
        )}
        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load skills"
            description="The skills list is unavailable right now."
            onRetry={() => {
              void refetch();
            }}
            retryLabel="Retry"
          />
        )}
        {!isLoading && !error && skills.length === 0 && total === 0 && !search && !sourceFilter && (
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
        {!isLoading && !error && skills.length === 0 && (search || sourceFilter) && (
          <div className="py-8 text-center text-[0.8rem]" style={{ color: "var(--ink-3)" }}>
            No skills match.
          </div>
        )}

        {skills.map((skill) => (
          <div
            key={skill.id}
            className="flex items-center gap-3 px-0 py-3.5"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <div className="flex-1 min-w-0">
              <div
                className="font-medium text-[0.875rem] flex items-center gap-2"
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

        <div className="pt-4">
          <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
        </div>
      </div>

      {drawer && (
        <SkillDrawer mode={drawer} canManage={canManage} onClose={() => setDrawer(null)} />
      )}
    </>
  );
}