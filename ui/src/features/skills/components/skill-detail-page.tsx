"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Pencil, Save, Trash2, Upload, X } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { useSkillFiles } from "../hooks/use-skill-files";
import { useSkillVersions } from "../hooks/use-skill-versions";
import { useSkillVersionDetail } from "../hooks/use-skill-version-detail";
import {
  type SkillFilePayload,
  type SkillUpdatePayload,
  useDeleteSkill,
  useDiscardSkillDraft,
  usePublishSkillDraft,
  useStartSkillDraft,
  useUpdateSkill,
  useUpdateSkillDraft,
} from "../hooks/use-skill-mutations";
import { ALL_PROVIDERS } from "../utils";
import { SkillDetailSidebar, type SkillDetailSection } from "./skill-detail-sidebar";
import { SkillFileBrowser } from "./skill-file-browser";
import { SkillRequiredProviders } from "./skill-required-providers";
import { SkillSourceBadge } from "./skill-source-badge";
import { SkillVersionHistory } from "./skill-version-history";

type Confirmation = "discard" | "publish" | "delete";

export function SkillDetailPage({ skillId }: { skillId: string }) {
  const { canManage } = useActiveOrgRole();
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const skillsHref = orgId ? `/dashboard/${orgId}/settings?tab=skills` : "/dashboard";

  const { detail, isLoading, error, refetch } = useSkillFiles(skillId);
  const { versions, isLoading: versionsLoading } = useSkillVersions(skillId);

  const [section, setSection] = useState<SkillDetailSection>("files");
  const [editing, setEditing] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [localFiles, setLocalFiles] = useState<SkillFilePayload[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [restoringVersion, setRestoringVersion] = useState<number | null>(null);

  const startDraft = useStartSkillDraft();
  const updateDraft = useUpdateSkillDraft();
  const discardDraft = useDiscardSkillDraft();
  const publishDraft = usePublishSkillDraft();
  const updateSkill = useUpdateSkill();
  const deleteSkill = useDeleteSkill();

  const latestVersion = Math.max(0, ...versions.map((v) => v.version));
  const viewingHistorical = selectedVersion !== null && selectedVersion !== latestVersion;
  const { files: historicalFiles, isLoading: historicalLoading } = useSkillVersionDetail(
    viewingHistorical ? skillId : null,
    viewingHistorical ? selectedVersion : null,
  );

  const isPending =
    startDraft.isPending || updateDraft.isPending || discardDraft.isPending || publishDraft.isPending || updateSkill.isPending;
  const mutationError =
    startDraft.error ?? updateDraft.error ?? discardDraft.error ?? publishDraft.error ?? updateSkill.error;

  if (isLoading) {
    return (
      <div className="af-page">
        <div className="af-card px-6 py-8 animate-pulse">
          <div className="h-6 w-56 rounded-md mb-3" style={{ background: "var(--bg-soft)" }} />
          <div className="h-3 w-72 rounded-md" style={{ background: "var(--bg-soft)" }} />
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="af-page">
        <Link
          href={skillsHref}
          className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--ink-3)" }}
        >
          <ArrowLeft size={14} /> Skills
        </Link>
        <AppErrorState
          error={error}
          title="We couldn't load this skill"
          description="The skill may have been deleted or is unavailable."
          onRetry={() => void refetch()}
          retryLabel="Retry"
          className="min-h-[15rem] p-0"
        />
      </div>
    );
  }

  const isCustom = detail.source === "custom";
  const canEdit = isCustom && canManage;
  const displayedFiles = viewingHistorical ? historicalFiles : detail.files;

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function enterEditing(sourceVersion?: number) {
    try {
      const draft = await startDraft.mutateAsync({ skillId, sourceVersion });
      setLocalFiles(draft.files);
      setName(detail!.name);
      setDescription(detail!.description ?? "");
      setSelectedProviders(detail!.requiredProviders);
      setFileError(null);
      setEditing(true);
      setSection("files");
      setSelectedVersion(null);
    } catch {
      // error rendered via mutationError
    } finally {
      setRestoringVersion(null);
    }
  }

  function handleRestoreVersion(version: number) {
    setRestoringVersion(version);
    void enterEditing(version);
  }

  function exitEditing() {
    setEditing(false);
    setLocalFiles(null);
    setFileError(null);
  }

  function handleDiscard() {
    setConfirmation("discard");
  }

  async function confirmDiscard() {
    setConfirmation(null);
    try {
      await discardDraft.mutateAsync(skillId);
      exitEditing();
    } catch {
      // error rendered via mutationError
    }
  }

  function validateEntry(files: SkillFilePayload[]): boolean {
    if (!files.some((f) => f.path === detail!.entryPath)) {
      setFileError(`A skill must include its entry point, ${detail!.entryPath}.`);
      return false;
    }
    return true;
  }

  async function handleSaveDraft() {
    if (!localFiles || !validateEntry(localFiles)) return;
    setFileError(null);
    try {
      const metadataPayload: SkillUpdatePayload = {
        skillId,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        requiredProviders: selectedProviders,
      };
      const [, draft] = await Promise.all([
        updateSkill.mutateAsync(metadataPayload),
        updateDraft.mutateAsync({ skillId, files: localFiles }),
      ]);
      setLocalFiles(draft.files);
    } catch {
      // error rendered via mutationError
    }
  }

  function handlePublish() {
    if (!localFiles || !validateEntry(localFiles)) return;
    setConfirmation("publish");
  }

  async function confirmPublish() {
    if (!localFiles) return;
    setConfirmation(null);
    try {
      const metadataPayload: SkillUpdatePayload = {
        skillId,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        requiredProviders: selectedProviders,
      };
      await Promise.all([
        updateSkill.mutateAsync(metadataPayload),
        updateDraft.mutateAsync({ skillId, files: localFiles }),
      ]);
      await publishDraft.mutateAsync(skillId);
      exitEditing();
    } catch {
      // error rendered via mutationError
    }
  }

  function handleDelete() {
    setConfirmation("delete");
  }

  async function confirmDelete() {
    setConfirmation(null);
    try {
      await deleteSkill.mutateAsync(skillId);
      router.push(skillsHref);
    } catch {
      // error rendered via deleteSkill.error
    }
  }

  const confirmationConfig =
    confirmation === "discard"
      ? {
          title: "Discard draft?",
          description: `Discard the unpublished draft for ${detail.name}? The last published version will remain unchanged.`,
          confirmLabel: "Discard draft",
          pendingLabel: "Discarding…",
          onConfirm: confirmDiscard,
          isPending: discardDraft.isPending,
          variant: "destructive" as const,
          icon: <Trash2 size={18} />,
        }
      : confirmation === "publish"
        ? {
            title: "Publish this draft?",
            description: `Publish ${detail.name} as a new version? Agents assigned this skill pick it up the next time they're restarted.`,
            confirmLabel: "Publish this version",
            pendingLabel: "Publishing…",
            onConfirm: confirmPublish,
            isPending: publishDraft.isPending || updateDraft.isPending || updateSkill.isPending,
            icon: <Upload size={18} />,
          }
        : confirmation === "delete"
          ? {
              title: "Delete this skill?",
              description: `Delete ${detail.name}? This cannot be undone.`,
              confirmLabel: "Delete skill",
              pendingLabel: "Deleting…",
              onConfirm: confirmDelete,
              isPending: deleteSkill.isPending,
              variant: "destructive" as const,
              icon: <Trash2 size={18} />,
            }
          : null;

  return (
    <div className="af-page">
      <Link
        href={skillsHref}
        className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
        style={{ color: "var(--ink-3)" }}
      >
        <ArrowLeft size={14} /> Skills
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-[1.75rem] font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              {detail.name}
            </h1>
            <SkillSourceBadge source={detail.source} />
            {detail.hasDraft && <Badge variant="warn">Draft in progress</Badge>}
          </div>
          <div className="text-[13px] font-mono mt-1" style={{ color: "var(--ink-3)" }}>
            v{latestVersion} · ./skills/{detail.rootDir}/{detail.entryPath}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {editing ? (
            <button className="af-btn" onClick={exitEditing} disabled={isPending}>
              <X size={14} /> Close
            </button>
          ) : (
            canEdit && (
              <>
                <button
                  className="af-btn"
                  style={{ borderColor: "var(--err)", color: "var(--err)" }}
                  onClick={handleDelete}
                >
                  <Trash2 size={14} /> Delete
                </button>
                <button className="af-btn af-btn-primary" onClick={() => void enterEditing()} disabled={isPending}>
                  {startDraft.isPending ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                  {detail.hasDraft ? "Continue editing draft" : "Edit"}
                </button>
              </>
            )
          )}
        </div>
      </div>

      <div className="flex gap-8 items-start flex-col lg:flex-row">
        <SkillDetailSidebar activeSection={section} onSectionChange={setSection} />

        <section className="flex-1 min-w-0">
          {mutationError instanceof Error && (
            <div
              className="rounded-xl px-4 py-3 mb-5"
              style={{ background: "var(--err-soft)", border: "1px solid color-mix(in srgb, var(--err) 30%, transparent)" }}
            >
              <div className="font-medium text-[13px]" style={{ color: "var(--err)" }}>
                Could not complete the request
              </div>
              <div className="text-[12.5px] mt-0.5" style={{ color: "var(--err)" }}>
                {mutationError.message}
              </div>
            </div>
          )}

          {section === "history" ? (
            <div className="af-card px-6 py-6">
              <h2 className="text-[14px] font-semibold m-0 mb-4" style={{ color: "var(--ink)" }}>
                Version history
              </h2>
              <SkillVersionHistory
                versions={versions}
                isLoading={versionsLoading}
                canManage={canEdit}
                hasDraft={detail.hasDraft}
                onRestore={handleRestoreVersion}
                restoringVersion={restoringVersion}
              />
            </div>
          ) : editing ? (
            <div className="af-card overflow-hidden">
              <div className="border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
                <p className="text-[13px] leading-[1.5] m-0" style={{ color: "var(--ink-3)" }}>
                  Agents currently using this skill will keep running the published version until
                  they are restarted after you publish.
                </p>
              </div>

              <div className="px-6 py-6 flex flex-col gap-6">
                <section className="flex flex-col gap-4">
                  <label
                    className="flex flex-col gap-1.5 text-[13px] font-medium"
                    style={{ color: "var(--ink-2)" }}
                  >
                    Name
                    <input
                      className="af-input"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      maxLength={255}
                    />
                  </label>
                  <label
                    className="flex flex-col gap-1.5 text-[13px] font-medium"
                    style={{ color: "var(--ink-2)" }}
                  >
                    Description
                    <input
                      className="af-input"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      maxLength={2000}
                      placeholder="What this skill helps the agent do"
                    />
                  </label>
                  <div className="flex flex-col gap-2">
                    <span className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
                      Required providers
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {ALL_PROVIDERS.map(({ value, label }) => {
                        const selected = selectedProviders.includes(value);
                        return (
                          <button
                            key={value}
                            type="button"
                            onClick={() => toggleProvider(value)}
                            className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors"
                            style={
                              selected
                                ? { background: "var(--ink)", color: "var(--bg)", border: "1px solid var(--ink)" }
                                : { background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }
                            }
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </section>

                <section className="flex flex-col gap-3">
                  <h3 className="text-[14px] font-semibold m-0" style={{ color: "var(--ink)" }}>
                    Files
                  </h3>
                  <SkillFileBrowser
                    files={localFiles ?? []}
                    entryPath={detail.entryPath}
                    onFilesChange={(files) => {
                      setLocalFiles(files);
                      setFileError(null);
                    }}
                  />
                  {fileError && (
                    <span className="text-xs" style={{ color: "var(--err)" }}>
                      {fileError}
                    </span>
                  )}
                </section>
              </div>

              <div className="border-t px-6 py-4" style={{ borderColor: "var(--line)" }}>
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                  <button className="af-btn af-btn-danger" onClick={handleDiscard} disabled={isPending}>
                    <Trash2 size={14} /> Discard
                  </button>
                  <div className="flex items-center gap-2">
                    <button className="af-btn" onClick={() => void handleSaveDraft()} disabled={isPending}>
                      {updateDraft.isPending || updateSkill.isPending ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Save size={14} />
                      )}{" "}
                      Save draft
                    </button>
                    <button className="af-btn af-btn-primary" onClick={handlePublish} disabled={isPending}>
                      {publishDraft.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}{" "}
                      Publish
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="af-card overflow-hidden">
              <div
                className="border-b px-6 py-5 flex flex-wrap items-center justify-between gap-3"
                style={{ borderColor: "var(--line)" }}
              >
                <p className="text-[13px] leading-[1.5] m-0" style={{ color: "var(--ink-3)" }}>
                  This published version is read-only.
                </p>
                {versions.length > 0 && (
                  <Select
                    value={String(selectedVersion ?? latestVersion)}
                    onValueChange={(value) => setSelectedVersion(Number(value))}
                  >
                    <SelectTrigger className="w-auto min-w-32" aria-label="Version">
                      <SelectValue placeholder="Select version" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {versions.map((v) => (
                          <SelectItem key={v.version} value={String(v.version)}>
                            Version v{v.version}
                            {v.version === latestVersion ? " (current)" : ""}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                )}
              </div>

              <div className="px-6 py-6 flex flex-col gap-6">
                {detail.description && (
                  <section>
                    <h2 className="text-[14px] font-semibold m-0 mb-2" style={{ color: "var(--ink)" }}>
                      Description
                    </h2>
                    <p className="text-[13.5px] leading-[1.6] m-0" style={{ color: "var(--ink-2)" }}>
                      {detail.description}
                    </p>
                  </section>
                )}

                <section>
                  <h2 className="text-[14px] font-semibold m-0 mb-2" style={{ color: "var(--ink)" }}>
                    Required integrations
                  </h2>
                  <SkillRequiredProviders providers={detail.requiredProviders} />
                </section>

                <section className="flex flex-col gap-3">
                  <h2 className="text-[14px] font-semibold m-0" style={{ color: "var(--ink)" }}>
                    Files
                  </h2>
                  {viewingHistorical && historicalLoading ? (
                    <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>
                      Loading version…
                    </div>
                  ) : (
                    <SkillFileBrowser files={displayedFiles} entryPath={detail.entryPath} readOnly />
                  )}
                </section>
              </div>
            </div>
          )}
        </section>
      </div>

      {confirmationConfig && (
        <ConfirmationDialog
          open={confirmation !== null}
          onOpenChange={(open) => {
            if (!open) setConfirmation(null);
          }}
          {...confirmationConfig}
        />
      )}
    </div>
  );
}
