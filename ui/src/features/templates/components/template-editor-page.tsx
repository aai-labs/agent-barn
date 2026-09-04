"use client";

import { ArrowLeft } from "lucide-react";
import { useParams, useRouter } from "next/navigation";

import { AppErrorState } from "@/components/app-error-state";

import { useTemplateLineages } from "../hooks/use-template-lineages";
import { templateDetailHref, templatesListHref, type TemplateScopeRef } from "../scope";
import { TemplateEditor } from "./template-editor";

export function TemplateEditorPage({
  scope,
  templateKey,
  isNew = false,
  canManage = true,
}: {
  scope: TemplateScopeRef;
  templateKey?: string;
  isNew?: boolean;
  canManage?: boolean;
}) {
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const listHref = templatesListHref(scope, orgId);
  const { lineages, isLoading, error, refetch } = useTemplateLineages(scope, !isNew);
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
        title="We couldn&apos;t load this template"
        description="The template editor is unavailable right now."
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
            Template not found
          </div>
          <p className="text-[13.5px] mb-5" style={{ color: "var(--ink-3)" }}>
            This template lineage may have been removed or is not available to
            your account.
          </p>
          <button
            className="af-btn"
            onClick={() => router.push(listHref)}
          >
            <ArrowLeft size={14} /> Back to templates
          </button>
        </div>
      </div>
    );
  }

  return (
    <TemplateEditor
      scope={scope}
      canManage={canManage}
      isNew={isNew}
      templateKey={isNew ? null : (templateKey ?? null)}
      lineage={lineage}
      onClose={() => router.push(listHref)}
      onCreated={(createdTemplateKey) =>
        router.replace(templateDetailHref(scope, orgId, createdTemplateKey))
      }
      onChanged={() => void refetch()}
    />
  );
}
