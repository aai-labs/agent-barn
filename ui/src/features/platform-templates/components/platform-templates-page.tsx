"use client";

import { FileText, Loader2, Pencil, Plus } from "lucide-react";
import { useRouter } from "next/navigation";

import { AppErrorState } from "@/components/app-error-state";

import { usePlatformTemplateLineages } from "../hooks/use-platform-template-lineages";

function LoadingLineageCard() {
  return (
    <div className="af-card px-5 py-5 animate-pulse">
      <div
        className="h-4 w-44 rounded-md mb-3"
        style={{ background: "var(--bg-soft)" }}
      />
      <div
        className="h-3 w-64 rounded-md mb-5"
        style={{ background: "var(--bg-soft)" }}
      />
      <div
        className="h-3 w-28 rounded-md"
        style={{ background: "var(--bg-soft)" }}
      />
    </div>
  );
}

export function PlatformTemplatesPage() {
  const router = useRouter();
  const { lineages, isLoading, error, refetch } = usePlatformTemplateLineages();

  return (
    <div className="max-w-[1200px] mx-auto px-10 pt-9 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-8">
        <div>
          <h1
            className="text-[28px] font-semibold tracking-tight m-0 mb-1"
            style={{ color: "var(--ink)" }}
          >
            Platform templates
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            Author the global agent prompts that organizations can use.
          </p>
        </div>
        <button
          className="af-btn af-btn-primary"
          onClick={() => router.push("/dashboard/platform/templates/new")}
        >
          <Plus size={15} /> New template
        </button>
      </div>

      <div className="flex items-center justify-between mb-4">
        <p className="text-[13px] m-0" style={{ color: "var(--ink-4)" }}>
          {lineages.length} {lineages.length === 1 ? "template lineage" : "template lineages"}
        </p>
        <button
          className="af-btn af-btn-sm"
          onClick={() => void refetch()}
          disabled={isLoading}
        >
          {isLoading ? <Loader2 size={13} className="animate-spin" /> : "Refresh"}
        </button>
      </div>

      {isLoading && (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}
        >
          {Array.from({ length: 6 }).map((_, index) => (
            <LoadingLineageCard key={index} />
          ))}
        </div>
      )}

      {!isLoading && Boolean(error) && (
        <AppErrorState
          error={error}
          title="We couldn't load platform templates"
          description="The platform template catalog is unavailable right now."
          onRetry={() => void refetch()}
          retryLabel="Retry templates"
          className="min-h-[260px] p-0"
        />
      )}

      {!isLoading && !error && lineages.length === 0 && (
        <div
          className="flex flex-col items-center justify-center text-center py-16 rounded-2xl"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <FileText size={22} style={{ color: "var(--ink-4)" }} />
          <div
            className="font-medium text-[15px] mt-3 mb-1"
            style={{ color: "var(--ink)" }}
          >
            No platform templates yet
          </div>
          <div className="text-[13.5px] mb-4" style={{ color: "var(--ink-3)" }}>
            Start a draft to create the first global agent template.
          </div>
          <button
            className="af-btn af-btn-primary"
            onClick={() => router.push("/dashboard/platform/templates/new")}
          >
            <Plus size={15} /> Create template
          </button>
        </div>
      )}

      {!isLoading && !error && lineages.length > 0 && (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}
        >
          {lineages.map((lineage) => (
            <button
              key={lineage.templateKey}
              type="button"
              className="af-card af-card-hover px-5 py-5 text-left w-full"
              onClick={() =>
                router.push(`/dashboard/platform/templates/${lineage.templateKey}`)
              }
            >
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText
                    size={15}
                    style={{ color: "var(--ink-4)", flexShrink: 0 }}
                  />
                  <span
                    className="font-semibold text-[15px] truncate"
                    style={{ color: "var(--ink)" }}
                  >
                    {lineage.templateName}
                  </span>
                </div>
                {lineage.hasDraft ? (
                  <span
                    className="flex-shrink-0 text-[11.5px] font-semibold px-2 py-0.5 rounded-full"
                    style={{ color: "var(--warn)", background: "var(--warn-soft)" }}
                  >
                    Draft
                  </span>
                ) : (
                  <span
                    className="flex-shrink-0 text-[11.5px] font-medium px-2 py-0.5 rounded-full"
                    style={{ color: "var(--ink-3)", background: "var(--bg-soft)" }}
                  >
                    Published
                  </span>
                )}
              </div>
              <div
                className="flex items-center justify-between text-[12.5px]"
                style={{ color: "var(--ink-3)" }}
              >
                <span>
                  {lineage.latestPublishedVersion === null
                    ? "Not published"
                    : `Published v${lineage.latestPublishedVersion}`}
                </span>
                <span
                  className="flex items-center gap-1.5"
                  style={{ color: "var(--ink-4)" }}
                >
                  <Pencil size={12} /> Manage
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
