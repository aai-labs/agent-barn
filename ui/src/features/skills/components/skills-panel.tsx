"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
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

import { type SkillSource } from "../schemas";
import { useSkills } from "../hooks/use-skills";
import { SKILLS_PAGE_SIZE } from "../utils";
import { SkillCard } from "./skill-card";

const SOURCE_FILTERS: Array<{ value: SkillSource | ""; label: string }> = [
  { value: "", label: "All sources" },
  { value: "aai_cli", label: "Built in" },
  { value: "custom", label: "Custom" },
];

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

export function SkillsPanel() {
  const { canManage } = useActiveOrgRole();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SkillSource | "">("");
  const [page, setPage] = useState(1);

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

  function skillHref(skillId: string) {
    return orgId ? `/dashboard/${orgId}/settings/skills/${skillId}` : "#";
  }

  const newSkillHref = orgId ? `/dashboard/${orgId}/settings/skills/new` : "#";

  return (
    <>
      <Hint>
        <ShieldIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Built-in skills are provided by AAI Labs and can be viewed but not modified. Custom skills
        are written by your organization and can be assigned to agents.
      </Hint>

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
          <Link href={newSkillHref} className="af-btn af-btn-primary ml-auto">
            <PlusIcon /> New skill
          </Link>
        )}
      </div>

      {isLoading && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
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
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          No skills match.
        </div>
      )}

      {!isLoading && !error && skills.length > 0 && (
        <div
          className="grid gap-4 mb-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
        >
          {skills.map((skill) => (
            <SkillCard key={skill.id} skill={skill} href={skillHref(skill.id)} />
          ))}
        </div>
      )}

      <div className="pt-4">
        <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </>
  );
}
