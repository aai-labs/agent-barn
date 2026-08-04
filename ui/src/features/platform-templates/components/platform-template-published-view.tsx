"use client";

import { useState } from "react";
import { ArrowLeft, Loader2, Pencil } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";

import type {
  PlatformTemplateAdminSummary,
  PlatformTemplate as PublishedPlatformTemplate,
} from "../schemas";
import {
  formFromDraft,
  type PlatformTemplateFileKey,
} from "../utils";
import { PlatformTemplateArtifactTabs } from "./platform-template-artifact-tabs";

export function PlatformTemplatePublishedView({
  lineage,
  template,
  versions,
  selectedVersion,
  isLoading,
  error,
  isStartingDraft,
  onRetry,
  onVersionChange,
  onStartEditing,
  onClose,
}: {
  lineage: PlatformTemplateAdminSummary | null;
  template: PublishedPlatformTemplate | undefined;
  versions: PublishedPlatformTemplate[];
  selectedVersion: number | null;
  isLoading: boolean;
  error: unknown;
  isStartingDraft: boolean;
  onRetry: () => void;
  onVersionChange: (version: number) => void;
  onStartEditing: () => void;
  onClose: () => void;
}) {
  const [selectedFile, setSelectedFile] =
    useState<PlatformTemplateFileKey>("soulMd");
  const templateForm = template ? formFromDraft(template) : null;
  const latestPublishedVersion = Math.max(
    0,
    ...versions.map(({ version }) => version),
  );
  const isCurrentVersion = template?.version === latestPublishedVersion;

  return (
    <div className="max-w-[1100px] mx-auto px-4 sm:px-8 lg:px-10 pt-8 pb-24">
      <button className="af-btn af-btn-sm mb-6" onClick={onClose}>
        <ArrowLeft size={14} /> Platform templates
      </button>

      {isLoading && (
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
      )}

      {!isLoading && Boolean(error) && (
        <AppErrorState
          error={error}
          title="We couldn't load this platform template"
          description="The published template content is unavailable right now."
          onRetry={onRetry}
          retryLabel="Retry template"
          className="p-0"
        />
      )}

      {!isLoading && !error && template && templateForm && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-4 mb-7">
            <div className="min-w-0">
              <h1
                className="text-[28px] font-semibold tracking-tight m-0 mb-1 truncate"
                style={{ color: "var(--ink)" }}
              >
                {template.templateName}
              </h1>
              <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
                {template.templateSlug} · Version v{template.version}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <select
                className="af-select"
                aria-label="Published version"
                value={selectedVersion === null ? "" : String(selectedVersion)}
                onChange={(event) =>
                  onVersionChange(Number(event.target.value))
                }
              >
                {versions.map((version) => (
                  <option key={version.id} value={version.version}>
                    Version v{version.version}
                  </option>
                ))}
              </select>
              <span
                className="flex-shrink-0 text-[11.5px] font-semibold px-2.5 py-1 rounded-full"
                style={
                  isCurrentVersion
                    ? { color: "var(--ok)", background: "var(--ok-soft)" }
                    : { color: "var(--ink-3)", background: "var(--bg-soft)" }
                }
              >
                {isCurrentVersion ? "Current" : "Historical"}
              </span>
              {lineage?.hasDraft && (
                <span
                  className="flex-shrink-0 text-[11.5px] font-semibold px-2.5 py-1 rounded-full"
                  style={{
                    color: "var(--warn)",
                    background: "var(--warn-soft)",
                  }}
                >
                  Draft in progress
                </span>
              )}
            </div>
          </div>

          <div className="af-card overflow-hidden">
            <div
              className="border-b px-6 py-5"
              style={{ borderColor: "var(--line)" }}
            >
              <p
                className="text-[13px] leading-[1.5] m-0"
                style={{ color: "var(--ink-3)" }}
              >
                This published version is read-only. Restore it as a new draft
                to roll the lineage back without altering its immutable history.
              </p>
            </div>

            <div className="px-6 py-6 flex flex-col gap-6">
              {template.description && (
                <section>
                  <h2
                    className="text-[14px] font-semibold m-0 mb-2"
                    style={{ color: "var(--ink)" }}
                  >
                    Description
                  </h2>
                  <p
                    className="text-[13.5px] leading-[1.6] m-0"
                    style={{ color: "var(--ink-2)" }}
                  >
                    {template.description}
                  </p>
                </section>
              )}

              <section className="flex flex-col gap-3">
                <div>
                  <h2
                    className="text-[14px] font-semibold m-0"
                    style={{ color: "var(--ink)" }}
                  >
                    Prompt artifacts
                  </h2>
                  <p
                    className="text-[12.5px] mt-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Markdown files rendered into agents using this platform
                    template.
                  </p>
                </div>
                <PlatformTemplateArtifactTabs
                  value={selectedFile}
                  onValueChange={setSelectedFile}
                  renderContent={({ key, label }) => (
                    <pre
                      className="af-input min-h-[360px] overflow-auto whitespace-pre-wrap font-mono text-[12.5px] leading-[1.65]"
                      aria-label={`${label} content`}
                    >
                      {templateForm.files[key]}
                    </pre>
                  )}
                />
              </section>

              <section>
                <h2
                  className="text-[14px] font-semibold m-0 mb-2"
                  style={{ color: "var(--ink)" }}
                >
                  Required skills
                </h2>
                {template.requiredSkills.length === 0 ? (
                  <p
                    className="text-[13px] m-0"
                    style={{ color: "var(--ink-4)" }}
                  >
                    No required skills.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {template.requiredSkills.map((skill) => (
                      <span
                        key={skill.id}
                        className="rounded-full px-2.5 py-1 text-[12px]"
                        style={{
                          color: "var(--ink-2)",
                          background: "var(--bg-soft)",
                          border: "1px solid var(--line)",
                        }}
                      >
                        {skill.groupKey ? `${skill.groupKey}: ` : ""}
                        {skill.name}
                      </span>
                    ))}
                  </div>
                )}
              </section>
            </div>

            <div
              className="border-t px-6 py-4"
              style={{ borderColor: "var(--line)" }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button className="af-btn" onClick={onClose}>
                  Close
                </button>
                <button
                  className="af-btn af-btn-primary"
                  onClick={onStartEditing}
                  disabled={isStartingDraft}
                >
                  {isStartingDraft ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Pencil size={14} />
                  )}
                  {lineage?.hasDraft
                    ? "Continue editing draft"
                    : template.version === versions[0]?.version
                      ? "Start draft"
                      : `Restore v${template.version} as draft`}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
