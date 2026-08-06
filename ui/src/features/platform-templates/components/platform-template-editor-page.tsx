"use client";

import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";

import { AppErrorState } from "@/components/app-error-state";

import { usePlatformTemplateLineages } from "../hooks/use-platform-template-lineages";
import { PlatformTemplateEditor } from "./platform-template-editor";

export function PlatformTemplateEditorPage({
  templateKey,
  isNew = false,
}: {
  templateKey?: string;
  isNew?: boolean;
}) {
  const router = useRouter();
  const { lineages, isLoading, error, refetch } =
    usePlatformTemplateLineages(!isNew);
  const lineage = isNew
    ? null
    : (lineages.find((candidate) => candidate.templateKey === templateKey) ?? null);

  if (!isNew && isLoading) {
    return (
      <div className="max-w-[1100px] mx-auto px-10 pt-9 pb-24">
        <div className="af-card px-6 py-8 animate-pulse">
          <div
            className="h-6 w-56 rounded-md mb-3"
            style={{ background: "var(--bg-soft)" }}
          />
          <div
            className="h-3 w-72 rounded-md"
            style={{ background: "var(--bg-soft)" }}
          />
        </div>
      </div>
    );
  }

  if (!isNew && error) {
    return (
      <AppErrorState
        error={error}
        title="We couldn't load this platform template"
        description="The platform template editor is unavailable right now."
        onRetry={() => void refetch()}
        retryLabel="Retry template"
      />
    );
  }

  if (!isNew && !lineage) {
    return (
      <div className="max-w-[1100px] mx-auto px-10 pt-9 pb-24">
        <div className="af-card px-6 py-8">
          <div
            className="font-semibold text-[16px] mb-1"
            style={{ color: "var(--ink)" }}
          >
            Platform template not found
          </div>
          <p className="text-[13.5px] mb-5" style={{ color: "var(--ink-3)" }}>
            This template lineage may have been removed or is not available to
            your account.
          </p>
          <button
            className="af-btn"
            onClick={() => router.push("/dashboard/platform/templates")}
          >
            <ArrowLeft size={14} /> Back to templates
          </button>
        </div>
      </div>
    );
  }

  return (
    <PlatformTemplateEditor
      isNew={isNew}
      templateKey={isNew ? null : (templateKey ?? null)}
      lineage={lineage}
      onClose={() => router.push("/dashboard/platform/templates")}
      onCreated={(createdTemplateKey) =>
        router.replace(`/dashboard/platform/templates/${createdTemplateKey}`)
      }
      onChanged={() => void refetch()}
    />
  );
}
