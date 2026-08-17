"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, GitFork, Loader2, Pencil, Save, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";

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

import { useSkillDraft } from "../hooks/use-skill-draft";
import { useSkillFiles } from "../hooks/use-skill-files";
import { useSkillVersions } from "../hooks/use-skill-versions";
import { useSkillVersionDetail } from "../hooks/use-skill-version-detail";
import {
  type SkillFilePayload,
  useDeleteSkillVersion,
  useDiscardSkillDraft,
  useForkSkill,
  usePublishSkillDraft,
  useStartSkillDraft,
  useUpdateSkillDraft,
} from "../hooks/use-skill-mutations";
import { SkillDetailSidebar, type SkillDetailSection } from "./skill-detail-sidebar";
import { SkillFileBrowser } from "./skill-file-browser";
import { SkillMetadataFields } from "./skill-metadata-fields";
import { SkillRequiredProviders } from "./skill-required-providers";
import { SkillSourceBadge } from "./skill-source-badge";
import { SkillVersionHistory } from "./skill-version-history";

type Confirmation = "discard" | "publish" | "delete-version" | "fork";

export function SkillDetailPage({ skillId }: { skillId: string }) {
  const { canManage } = useActiveOrgRole();
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const skillsHref = orgId ? `/dashboard/${orgId}/settings?tab=skills` : "/dashboard";

  const { detail, isLoading, error, refetch } = useSkillFiles(skillId);
  const { versions, isLoading: versionsLoading } = useSkillVersions(skillId);

  // After forking a built-in, the router lands here with ?edit=1. The editor
  // opens immediately, seeded from the persisted draft (fetched via useSkillDraft)
  // rather than the published version, so a page reload preserves unpublished
  // edits instead of overwriting them.
  const searchParams = useSearchParams();
  const autoOpenEditor = searchParams.get("edit") === "1";

  const [section, setSection] = useState<SkillDetailSection>("files");
  const [editing, setEditing] = useState(autoOpenEditor);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [localFiles, setLocalFiles] = useState<SkillFilePayload[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [deletingVersion, setDeletingVersion] = useState<number | null>(null);
  const [draftApplied, setDraftApplied] = useState(false);
  const [viewingDraft, setViewingDraft] = useState(false);

  const startDraft = useStartSkillDraft();
  const updateDraft = useUpdateSkillDraft();
  const discardDraft = useDiscardSkillDraft();
  const publishDraft = usePublishSkillDraft();
  const forkSkill = useForkSkill();
  const deleteSkillVersion = useDeleteSkillVersion();

  // Fetch the persisted draft whenever one is known to exist, so the
  // read-only view can preview it and ?edit=1 can hydrate from it.
  const { draft: existingDraft } = useSkillDraft(skillId, !!detail?.hasDraft);

  // Seed the auto-opened editor. When the draft query resolves, replace the
  // editor content with the persisted draft so unpublished edits survive a
  // reload. Guarded setState during render (the React "adjust state when a
  // prop arrives" pattern): the initial seed runs once when detail arrives,
  // and the draft seed runs once when the draft arrives, each guarded by a
  // distinct condition so user edits are never overwritten.
  if (editing && localFiles === null && detail) {
    setLocalFiles(detail.files);
    setName(detail.name);
    setDescription(detail.description ?? "");
    setSelectedProviders(detail.requiredProviders);
  }
  if (editing && existingDraft && localFiles !== null && !draftApplied) {
    const draftFiles = existingDraft.files.map((f) => ({ path: f.path, content: f.content }));
    setLocalFiles(draftFiles);
    setDraftApplied(true);
  }

  const latestVersion = Math.max(0, ...versions.map((v) => v.version));
  const viewingHistorical = selectedVersion !== null && selectedVersion !== latestVersion;
  const { files: historicalFiles, isLoading: historicalLoading } = useSkillVersionDetail(
    viewingHistorical ? skillId : null,
    viewingHistorical ? selectedVersion : null,
  );

  const isPending =
    startDraft.isPending || updateDraft.isPending || discardDraft.isPending || publishDraft.isPending;
  const mutationError =
    startDraft.error ?? updateDraft.error ?? discardDraft.error ?? publishDraft.error ?? forkSkill.error ?? deleteSkillVersion.error;

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
  const isBuiltIn = detail.source === "aai_cli";
  const canEdit = isCustom && canManage;
  const draftFiles = existingDraft?.files.map((f) => ({ path: f.path, content: f.content })) ?? [];
  const showDraftPreview = !editing && viewingDraft && existingDraft && detail.hasDraft;
  const displayedFiles = showDraftPreview
    ? draftFiles
    : viewingHistorical
      ? historicalFiles
      : detail.files;

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function enterEditing() {
    try {
      const draft = await startDraft.mutateAsync(skillId);
      setLocalFiles(draft.files);
      setName(detail!.name);
      setDescription(detail!.description ?? "");
      setSelectedProviders(detail!.requiredProviders);
      setFileError(null);
      setEditing(true);
      setViewingDraft(false);
      setSection("files");
      setSelectedVersion(null);
    } catch {
      // error rendered via mutationError
    }
  }

  function exitEditing() {
    setEditing(false);
    setLocalFiles(null);
    setFileError(null);
    setDraftApplied(false);
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
      const draft = await updateDraft.mutateAsync({
        skillId,
        files: localFiles,
        description: description.trim(),
        requiredProviders: selectedProviders,
      });
      setLocalFiles(draft.files.map((f) => ({ path: f.path, content: f.content })));
      toast.success("Draft saved.");
    } catch {
      // error rendered via mutationError
    }
  }

  function handlePublish() {
    setConfirmation("publish");
  }

  async function confirmPublish() {
    setConfirmation(null);
    try {
      const published = await publishDraft.mutateAsync(skillId);
      toast.success(`${detail!.name} v${published.version} published.`);
    } catch {
      // error rendered via mutationError
    }
  }

  function handleFork() {
    setConfirmation("fork");
  }

  async function confirmFork() {
    setConfirmation(null);
    try {
      const fork = await forkSkill.mutateAsync(skillId);
      router.push(orgId ? `/dashboard/${orgId}/settings/skills/${fork.id}?edit=1` : "/dashboard");
    } catch {
      // error rendered via mutationError
    }
  }

  function handleDeleteVersion(version: number) {
    setDeletingVersion(version);
    setConfirmation("delete-version");
  }

  async function confirmDeleteVersion() {
    setConfirmation(null);
    const version = deletingVersion;
    setDeletingVersion(null);
    if (version === null) return;
    try {
      await deleteSkillVersion.mutateAsync({ skillId, version });
      toast.success(`Version ${version} deleted.`);
    } catch {
      // error rendered via mutationError
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
            isPending: publishDraft.isPending,
            icon: <Upload size={18} />,
          }
        : confirmation === "delete-version"
          ? {
              title: `Delete version ${deletingVersion}?`,
              description: `Permanently remove version ${deletingVersion} of ${detail.name} from its history? This cannot be undone.`,
              confirmLabel: "Delete version",
              pendingLabel: "Deleting…",
              onConfirm: confirmDeleteVersion,
              isPending: deleteSkillVersion.isPending,
              variant: "destructive" as const,
              icon: <Trash2 size={18} />,
            }
          : confirmation === "fork"
            ? {
                title: "Fork this built-in skill?",
                description: `Create an editable copy of ${detail.name} for your organization? It publishes as its own custom skill version and opens a draft. The built-in skill stays read-only.`,
                confirmLabel: "Fork skill",
                pendingLabel: "Forking…",
                onConfirm: confirmFork,
                isPending: forkSkill.isPending,
                icon: <GitFork size={18} />,
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
          {isBuiltIn && canManage && !editing ? (
            <button className="af-btn" onClick={handleFork} disabled={forkSkill.isPending}>
              {forkSkill.isPending ? <Loader2 size={14} className="animate-spin" /> : <GitFork size={14} />}
              Fork
            </button>
          ) : null}
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
                onDelete={handleDeleteVersion}
                deletingVersion={deletingVersion}
              />
            </div>
          ) : editing ? (
            <div className="af-card overflow-hidden">
              <div className="border-b px-6 py-5 flex items-center justify-between gap-3" style={{ borderColor: "var(--line)" }}>
                <p className="text-[13px] leading-[1.5] m-0" style={{ color: "var(--ink-3)" }}>
                  Agents currently using this skill will keep running the published version until
                  they are restarted after you publish.
                </p>
                <button className="af-btn flex-shrink-0" onClick={exitEditing} disabled={isPending}>
                  <X size={14} /> Close
                </button>
              </div>

              <div className="px-6 py-6 flex flex-col gap-6">
                <SkillMetadataFields
                  name={name}
                  onNameChange={setName}
                  description={description}
                  onDescriptionChange={setDescription}
                  selectedProviders={selectedProviders}
                  onToggleProvider={toggleProvider}
                />

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
                  <button className="af-btn" onClick={() => void handleSaveDraft()} disabled={isPending}>
                    {updateDraft.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Save size={14} />
                    )}{" "}
                    Save draft
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="af-card overflow-hidden">
              <div
                className="border-b px-6 py-5 flex flex-wrap items-center justify-between gap-3"
                style={{ borderColor: "var(--line)" }}
              >
                <div className="flex items-center gap-3">
                  {detail.hasDraft && (
                    <div className="inline-flex rounded-lg" style={{ border: "1px solid var(--line)" }}>
                      <button
                        type="button"
                        className="px-3 py-1 text-[12.5px] font-medium transition-colors"
                        style={{
                          background: !viewingDraft ? "var(--bg-soft)" : "transparent",
                          color: !viewingDraft ? "var(--ink)" : "var(--ink-3)",
                        }}
                        onClick={() => setViewingDraft(false)}
                      >
                        Published v{latestVersion}
                      </button>
                      <button
                        type="button"
                        className="px-3 py-1 text-[12.5px] font-medium transition-colors"
                        style={{
                          background: viewingDraft ? "var(--bg-soft)" : "transparent",
                          color: viewingDraft ? "var(--ink)" : "var(--ink-3)",
                        }}
                        onClick={() => {
                          setViewingDraft(true);
                          setSelectedVersion(null);
                        }}
                      >
                        Draft
                      </button>
                    </div>
                  )}
                  {(!detail.hasDraft || !viewingDraft) && (
                    <p className="text-[13px] leading-[1.5] m-0" style={{ color: "var(--ink-3)" }}>
                      This published version is read-only.
                    </p>
                  )}
                </div>
                {/* Right side of the header: version selector (Published) or
                  Edit/Publish (Draft). Wrapped in a min-height container so
                  switching tabs doesn't cause a layout jump. */}
                <div className="flex items-center gap-2 min-h-[36px]">
                  {(!detail.hasDraft || !viewingDraft) && versions.length > 0 && (
                    <>
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
                      {canEdit && !detail.hasDraft && (
                        <button className="af-btn" onClick={() => void enterEditing()} disabled={isPending}>
                          {startDraft.isPending ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                          Edit
                        </button>
                      )}
                    </>
                  )}
                  {showDraftPreview && canEdit && (
                    <>
                      <button className="af-btn" onClick={() => void enterEditing()} disabled={isPending}>
                        {startDraft.isPending ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                        Edit
                      </button>
                      <button className="af-btn af-btn-primary" onClick={handlePublish} disabled={publishDraft.isPending}>
                        {publishDraft.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                        Publish
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className="px-6 py-6 flex flex-col gap-6">
                {/* Published tab: show the skill row's metadata (the last-published
                  values). Draft tab: show the draft's staged metadata. */}
                {showDraftPreview
                  ? existingDraft?.description && (
                      <section>
                        <h2 className="text-[14px] font-semibold m-0 mb-2" style={{ color: "var(--ink)" }}>
                          Description
                        </h2>
                        <p className="text-[13.5px] leading-[1.6] m-0" style={{ color: "var(--ink-2)" }}>
                          {existingDraft.description}
                        </p>
                      </section>
                    )
                  : detail.description && (
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
                  <SkillRequiredProviders
                    providers={showDraftPreview ? existingDraft?.requiredProviders ?? [] : detail.requiredProviders}
                  />
                </section>

                {showDraftPreview ? (
                  <section className="flex flex-col gap-3">
                    <h2 className="text-[14px] font-semibold m-0" style={{ color: "var(--ink)" }}>
                      Draft files
                    </h2>
                    <SkillFileBrowser files={displayedFiles} entryPath={detail.entryPath} readOnly />
                  </section>
                ) : (
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
                )}
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
