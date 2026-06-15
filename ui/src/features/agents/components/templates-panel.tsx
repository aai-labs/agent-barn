"use client";

import { useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { PlusIcon, SearchIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTemplates } from "../hooks/use-templates";
import type { AgentTemplateRead, TemplateSource } from "../schemas";
import { TemplateSourceBadge } from "./hire-dialog-steps";
import { TemplateDrawer } from "./template-drawer";

const SOURCE_FILTERS: Array<{ value: TemplateSource | ""; label: string }> = [
  { value: "", label: "All sources" },
  { value: "pre-defined", label: "Pre-defined" },
  { value: "custom", label: "Custom" },
];

export function TemplatesPanel() {
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<TemplateSource | "">("");
  const [openTemplate, setOpenTemplate] = useState<AgentTemplateRead | null>(null);
  const [creating, setCreating] = useState(false);

  const { templates, isLoading, error } = useTemplates({
    search: search || undefined,
    source: source || undefined,
  });

  return (
    <div>
      <div className="mb-4 flex items-center gap-2.5">
        <div className="relative flex-1">
          <input
            className="af-input pl-8.5 w-full"
            placeholder="Search templates…"
            aria-label="Search templates"
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
              {SOURCE_FILTERS.find((f) => f.value === source)?.label ?? "All sources"}
              <ChevronDownIcon size={13} className="opacity-50 flex-shrink-0" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuRadioGroup
              value={source}
              onValueChange={(v) => setSource(v as TemplateSource | "")}
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
        <button className="af-btn af-btn-primary ml-auto" onClick={() => setCreating(true)}>
          <PlusIcon /> New template
        </button>
      </div>

      {isLoading && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          Loading templates…
        </div>
      )}
      {error && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--err)" }}>
          Could not load templates.
        </div>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
          No templates match.
        </div>
      )}

      {templates.map((t) => (
        <div
          key={t.templateSlug}
          role="button"
          className="flex items-center gap-3 px-0 py-3.5 cursor-default"
          style={{ borderBottom: "1px solid var(--line)" }}
          onClick={() => setOpenTemplate(t)}
        >
          <div className="flex-1">
            <div className="font-medium text-[14px] flex items-center gap-2" style={{ color: "var(--ink)" }}>
              <span>{t.templateName}</span>
              <span className="font-mono text-[12px] font-normal" style={{ color: "var(--ink-4)" }}>
                · {t.templateSlug}@v{t.version}
              </span>
              <TemplateSourceBadge source={t.templateSource} />
            </div>
          </div>
          <button
            className="af-btn af-btn-sm af-btn-ghost"
            onClick={(e) => { e.stopPropagation(); setOpenTemplate(t); }}
          >
            View
          </button>
        </div>
      ))}

      {openTemplate && (
        <TemplateDrawer
          mode="view"
          slug={openTemplate.templateSlug}
          onClose={() => setOpenTemplate(null)}
        />
      )}
      {creating && (
        <TemplateDrawer mode="create" onClose={() => setCreating(false)} />
      )}
    </div>
  );
}
