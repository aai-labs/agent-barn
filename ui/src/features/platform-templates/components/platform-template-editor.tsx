"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CircleDashed,
  Eye,
  Loader2,
  Pencil,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import {
  useCreatePlatformTemplateDraft,
  useDiscardPlatformTemplateDraft,
  usePublishPlatformTemplateDraft,
  useStartPlatformTemplateDraft,
  useUpdatePlatformTemplateDraft,
} from "../hooks/use-platform-template-actions";
import { usePlatformSkills } from "../hooks/use-platform-skills";
import { usePlatformTemplateDraft } from "../hooks/use-platform-template-draft";
import { usePlatformTemplateVersions } from "../hooks/use-platform-template-versions";
import type { PlatformTemplateAdminSummary } from "../schemas";
import {
  blankPlatformTemplateFiles,
  formFromDraft,
  requiredSkillPayload,
  type PlatformTemplateFileKey,
  type PlatformTemplateForm,
} from "../utils";
import { PlatformTemplateArtifactTabs } from "./platform-template-artifact-tabs";
import { PlatformTemplatePublishedView } from "./platform-template-published-view";
import { PlatformTemplateSkillCheckbox } from "./platform-template-skill-checkbox";
import { PlatformTemplateSkillGroup } from "./platform-template-skill-group";

function emptyForm(): PlatformTemplateForm {
  return {
    templateName: "",
    description: "",
    files: blankPlatformTemplateFiles(),
    standaloneSkillIds: [],
    skillGroups: [],
  };
}

export function PlatformTemplateEditor({
  isNew,
  templateKey,
  lineage,
  onClose,
  onCreated,
  onChanged,
}: {
  isNew: boolean;
  templateKey: string | null;
  lineage: PlatformTemplateAdminSummary | null;
  onClose: () => void;
  onCreated: (templateKey: string) => void;
  onChanged: () => void;
}) {
  const hasPublishedVersion =
    !isNew && Boolean(lineage && lineage.latestPublishedVersion !== null);
  const [isEditing, setIsEditing] = useState(isNew || !hasPublishedVersion);
  const [started, setStarted] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const shouldLoadDraft =
    !isNew &&
    isEditing &&
    Boolean(lineage) &&
    (Boolean(lineage?.hasDraft) || started);
  const {
    versions: publishedVersions,
    isLoading: isPublishedLoading,
    error: publishedError,
    refetch: refetchPublishedVersions,
  } = usePlatformTemplateVersions(templateKey, hasPublishedVersion);
  const {
    draft,
    isLoading: isDraftLoading,
    error: draftError,
  } = usePlatformTemplateDraft(templateKey, shouldLoadDraft);
  const {
    skills,
    isLoading: isSkillsLoading,
    error: skillsError,
  } = usePlatformSkills(true);
  const startDraft = useStartPlatformTemplateDraft();
  const createDraft = useCreatePlatformTemplateDraft();
  const updateDraft = useUpdatePlatformTemplateDraft();
  const discardDraft = useDiscardPlatformTemplateDraft();
  const publishDraft = usePublishPlatformTemplateDraft();
  const [form, setForm] = useState<PlatformTemplateForm>(emptyForm);
  const [selectedFile, setSelectedFile] =
    useState<PlatformTemplateFileKey>("soulMd");
  const [skillSearch, setSkillSearch] = useState("");
  const [dirty, setDirty] = useState(false);
  const initializedDraftId = useRef<string | null>(null);

  const currentDraft = draft ?? startDraft.data;
  const canEdit = isNew || Boolean(currentDraft);
  const pending =
    startDraft.isPending ||
    createDraft.isPending ||
    updateDraft.isPending ||
    discardDraft.isPending ||
    publishDraft.isPending;
  const publishedTemplate = useMemo(
    () =>
      publishedVersions.find(
        (version) => version.version === selectedVersion,
      ) ?? publishedVersions[0],
    [publishedVersions, selectedVersion],
  );

  useEffect(() => {
    if (!currentDraft || initializedDraftId.current === currentDraft.id) return;
    initializedDraftId.current = currentDraft.id;
    setForm(formFromDraft(currentDraft));
    setDirty(false);
  }, [currentDraft]);

  const skillMap = useMemo(
    () => new Map(skills.map((skill) => [skill.id, skill])),
    [skills],
  );
  const selectedSkillIds = useMemo(
    () =>
      new Set([
        ...form.standaloneSkillIds,
        ...form.skillGroups.flatMap((group) => group.skillIds),
      ]),
    [form.skillGroups, form.standaloneSkillIds],
  );
  const visibleSkills = useMemo(() => {
    const normalized = skillSearch.trim().toLowerCase();
    if (!normalized) return skills;
    return skills.filter((skill) =>
      skill.name.toLowerCase().includes(normalized),
    );
  }, [skillSearch, skills]);

  function patchForm(
    updater: (previous: PlatformTemplateForm) => PlatformTemplateForm,
  ) {
    setForm((previous) => updater(previous));
    setDirty(true);
  }

  function setFileValue(value: string) {
    patchForm((previous) => ({
      ...previous,
      files: { ...previous.files, [selectedFile]: value },
    }));
  }

  function toggleStandaloneSkill(skillId: string) {
    patchForm((previous) => ({
      ...previous,
      standaloneSkillIds: previous.standaloneSkillIds.includes(skillId)
        ? previous.standaloneSkillIds.filter((id) => id !== skillId)
        : [...previous.standaloneSkillIds, skillId],
    }));
  }

  function toggleGroupSkill(groupKey: string, skillId: string) {
    patchForm((previous) => ({
      ...previous,
      skillGroups: previous.skillGroups.map((group) => {
        if (group.groupKey !== groupKey) return group;
        if (group.skillIds.includes(skillId)) {
          if (group.skillIds.length === 1) return group;
          return {
            ...group,
            skillIds: group.skillIds.filter((id) => id !== skillId),
          };
        }
        return { ...group, skillIds: [...group.skillIds, skillId] };
      }),
    }));
  }

  async function handleStartDraft() {
    if (isNew || !templateKey) return;
    try {
      const result = await startDraft.mutateAsync({ templateKey });
      setStarted(true);
      initializedDraftId.current = result.id;
      setForm(formFromDraft(result));
      setDirty(false);
    } catch {
      // The mutation error is rendered on the page.
    }
  }

  async function handleSave() {
    if (!canEdit) return;
    if (isNew && !form.templateName.trim()) {
      toast.error("Give the template a name before saving.");
      return;
    }

    const payload = {
      description: form.description.trim() || null,
      ...form.files,
      ...requiredSkillPayload(form),
    };

    try {
      if (isNew) {
        const created = await createDraft.mutateAsync({
          templateName: form.templateName.trim(),
          ...payload,
        });
        toast.success(`${created.templateName} draft created.`);
        onChanged();
        onCreated(created.templateKey);
        return;
      }

      const updated = await updateDraft.mutateAsync({
        templateKey: templateKey!,
        ...payload,
      });
      initializedDraftId.current = updated.id;
      setForm(formFromDraft(updated));
      setDirty(false);
      toast.success("Draft saved.");
      onChanged();
    } catch {
      // The mutation error is rendered on the page.
    }
  }

  async function handleDiscard() {
    if (!templateKey || !currentDraft) return;
    if (
      !window.confirm(
        "Discard this unpublished draft? The last published version will remain unchanged.",
      )
    )
      return;
    try {
      await discardDraft.mutateAsync(templateKey);
      toast.success("Draft discarded.");
      onChanged();
      onClose();
    } catch {
      // The mutation error is rendered on the page.
    }
  }

  async function handlePublish() {
    if (!templateKey || !currentDraft || dirty) return;
    if (
      !window.confirm(
        "Publish this draft? Organizations will be able to use the new platform version.",
      )
    )
      return;
    try {
      const published = await publishDraft.mutateAsync(templateKey);
      toast.success(
        `${currentDraft.templateName} v${published.version} published.`,
      );
      onChanged();
      onClose();
    } catch {
      // The mutation error is rendered on the page.
    }
  }

  function requestClose() {
    if (
      dirty &&
      !window.confirm("You have unsaved changes. Close without saving?")
    )
      return;
    onClose();
  }

  function viewPublishedVersion() {
    if (
      dirty &&
      !window.confirm(
        "You have unsaved changes. Leave draft editing? Your unsaved changes will be discarded.",
      )
    ) {
      return;
    }
    if (currentDraft) {
      setForm(formFromDraft(currentDraft));
      setDirty(false);
    }
    setIsEditing(false);
  }

  const mutationError =
    startDraft.error ??
    createDraft.error ??
    updateDraft.error ??
    discardDraft.error ??
    publishDraft.error;
  const editorError = mutationError ?? draftError ?? skillsError;
  const errorMessage =
    editorError instanceof Error ? editorError.message : null;
  const templateName = isNew
    ? form.templateName || "New platform template"
    : (currentDraft?.templateName ??
      lineage?.templateName ??
      "Platform template");
  const templateMeta = isNew
    ? "Create an unpublished template draft. It becomes visible to organizations only after publishing."
    : lineage?.latestPublishedVersion
      ? `Published v${lineage.latestPublishedVersion}`
      : "Not published";

  async function handleStartEditing() {
    if (!templateKey) return;
    if (lineage?.hasDraft) {
      setIsEditing(true);
      return;
    }

    try {
      const result = await startDraft.mutateAsync({
        templateKey,
        sourceVersion: publishedTemplate?.version,
      });
      setStarted(true);
      setIsEditing(true);
      initializedDraftId.current = result.id;
      setForm(formFromDraft(result));
      setDirty(false);
    } catch {
      // The mutation error is rendered on the page.
    }
  }

  if (!isEditing) {
    return (
      <PlatformTemplatePublishedView
        lineage={lineage}
        template={publishedTemplate}
        isLoading={isPublishedLoading}
        error={
          publishedError ??
          (mutationError instanceof Error ? mutationError : null)
        }
        isStartingDraft={startDraft.isPending}
        versions={publishedVersions}
        selectedVersion={publishedTemplate?.version ?? null}
        onRetry={() => void refetchPublishedVersions()}
        onVersionChange={setSelectedVersion}
        onStartEditing={() => void handleStartEditing()}
        onClose={requestClose}
      />
    );
  }

  return (
    <div className="max-w-[1100px] mx-auto px-4 sm:px-8 lg:px-10 pt-8 pb-24">
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          className="af-btn af-btn-sm"
          onClick={requestClose}
          disabled={pending}
        >
          <ArrowLeft size={14} /> Platform templates
        </button>
        {!isNew && hasPublishedVersion && (
          <button
            className="af-btn af-btn-sm"
            onClick={viewPublishedVersion}
            disabled={pending}
          >
            <Eye size={14} /> View published version
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4 mb-7">
        <div className="min-w-0">
          <h1
            className="text-[28px] font-semibold tracking-tight m-0 mb-1 truncate"
            style={{ color: "var(--ink)" }}
          >
            {templateName}
          </h1>
          <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
            {templateMeta}
          </p>
        </div>
        {!isNew && lineage?.hasDraft && currentDraft && (
          <span
            className="flex-shrink-0 text-[11.5px] font-semibold px-2.5 py-1 rounded-full"
            style={{ color: "var(--warn)", background: "var(--warn-soft)" }}
          >
            Draft in progress
          </span>
        )}
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
            {isNew
              ? "Define the prompt artifacts and required skills for this platform template. Save it as a draft before publishing."
              : "Edit the draft Markdown artifacts and required skills. Published versions remain immutable."}
          </p>
        </div>

        <div className="px-6 py-6">
          {errorMessage && (
            <div
              className="rounded-xl px-4 py-3 mb-5"
              style={{
                background: "var(--err-soft)",
                border:
                  "1px solid color-mix(in srgb, var(--err) 30%, transparent)",
              }}
            >
              <div
                className="font-medium text-[13px]"
                style={{ color: "var(--err)" }}
              >
                Could not complete the request
              </div>
              <div
                className="text-[12.5px] mt-0.5"
                style={{ color: "var(--err)" }}
              >
                {errorMessage}
              </div>
            </div>
          )}

          {!isNew && !currentDraft && isDraftLoading && (
            <div
              className="flex items-center gap-2 text-[13px]"
              style={{ color: "var(--ink-3)" }}
            >
              <Loader2 size={14} className="animate-spin" /> Loading draft…
            </div>
          )}

          {!isNew && !currentDraft && !isDraftLoading && !lineage?.hasDraft && (
            <div className="af-card px-5 py-5">
              <div className="flex items-center gap-2 mb-2">
                <CircleDashed size={16} style={{ color: "var(--ink-4)" }} />
                <div
                  className="font-semibold text-[15px]"
                  style={{ color: "var(--ink)" }}
                >
                  No draft in progress
                </div>
              </div>
              <p
                className="text-[13.5px] leading-[1.5] mb-5"
                style={{ color: "var(--ink-3)" }}
              >
                Start a draft from the latest published version, edit the
                Markdown artifacts, then save or publish it when ready.
              </p>
              <button
                className="af-btn af-btn-primary"
                onClick={() => void handleStartDraft()}
                disabled={pending}
              >
                {pending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Pencil size={14} />
                )}{" "}
                Start draft
              </button>
            </div>
          )}

          {canEdit && (
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4">
                <div>
                  <h3
                    className="text-[14px] font-semibold m-0"
                    style={{ color: "var(--ink)" }}
                  >
                    Template details
                  </h3>
                  <p
                    className="text-[12.5px] mt-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    The name is a display label; the system assigns the lineage key
                    automatically when it is saved.
                  </p>
                </div>
                <label
                  className="flex flex-col gap-1.5 text-[13px] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  Template name
                  <input
                    className="af-input"
                    aria-label="Template name"
                    value={form.templateName}
                    disabled={!isNew}
                    onChange={(event) =>
                      patchForm((previous) => ({
                        ...previous,
                        templateName: event.target.value,
                      }))
                    }
                    placeholder="Code reviewer"
                  />
                </label>
                <label
                  className="flex flex-col gap-1.5 text-[13px] font-medium"
                  style={{ color: "var(--ink-2)" }}
                >
                  Description
                  <textarea
                    className="af-input resize-y min-h-20"
                    aria-label="Description"
                    value={form.description}
                    maxLength={500}
                    onChange={(event) =>
                      patchForm((previous) => ({
                        ...previous,
                        description: event.target.value,
                      }))
                    }
                    placeholder="A short summary of what this template does…"
                  />
                </label>
              </section>

              <section className="flex flex-col gap-3">
                <div>
                  <h3
                    className="text-[14px] font-semibold m-0"
                    style={{ color: "var(--ink)" }}
                  >
                    Prompt artifacts
                  </h3>
                  <p
                    className="text-[12.5px] mt-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Edit the raw Markdown files that are rendered into agents
                    using this platform template.
                  </p>
                </div>
                <PlatformTemplateArtifactTabs
                  value={selectedFile}
                  onValueChange={setSelectedFile}
                  renderContent={({ key, label }) => (
                    <textarea
                      className="af-input font-mono text-[12.5px] leading-[1.65] resize-y min-h-[360px]"
                      aria-label={`${label} content`}
                      value={form.files[key]}
                      onChange={(event) => setFileValue(event.target.value)}
                      spellCheck={false}
                    />
                  )}
                />
              </section>

              <section className="flex flex-col gap-3">
                <div>
                  <h3
                    className="text-[14px] font-semibold m-0"
                    style={{ color: "var(--ink)" }}
                  >
                    Required skills
                  </h3>
                  <p
                    className="text-[12.5px] mt-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Only global platform skills can be required here. Standalone
                    skills are always required; grouped skills mean “at least
                    one of”.
                  </p>
                </div>
                <input
                  className="af-input"
                  aria-label="Search platform skills"
                  placeholder="Search global skills…"
                  value={skillSearch}
                  onChange={(event) => setSkillSearch(event.target.value)}
                />
                {isSkillsLoading && (
                  <div
                    className="text-[12.5px]"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Loading global skills…
                  </div>
                )}
                {skillsError && (
                  <div
                    className="text-[12.5px]"
                    style={{ color: "var(--err)" }}
                  >
                    Global skills could not be loaded.
                  </div>
                )}
                {!isSkillsLoading && !skillsError && (
                  <div className="flex flex-col gap-2">
                    {visibleSkills
                      .filter(
                        (skill) =>
                          !form.skillGroups.some((group) =>
                            group.skillIds.includes(skill.id),
                          ),
                      )
                      .map((skill) => (
                        <PlatformTemplateSkillCheckbox
                          key={skill.id}
                          skill={skill}
                          checked={form.standaloneSkillIds.includes(skill.id)}
                          onChange={() => toggleStandaloneSkill(skill.id)}
                        />
                      ))}
                    {form.skillGroups.map((group) => (
                      <PlatformTemplateSkillGroup
                        key={group.groupKey}
                        group={group}
                        skills={visibleSkills}
                        skillMap={skillMap}
                        selectedSkillIds={selectedSkillIds}
                        onToggle={(skillId) =>
                          toggleGroupSkill(group.groupKey, skillId)
                        }
                      />
                    ))}
                    {visibleSkills.length === 0 &&
                      form.skillGroups.length === 0 && (
                        <div
                          className="text-[12.5px]"
                          style={{ color: "var(--ink-4)" }}
                        >
                          No global skills match.
                        </div>
                      )}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>

        <div
          className="border-t px-6 py-4"
          style={{ borderColor: "var(--line)" }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 w-full">
            <div className="flex items-center gap-2">
              {!isNew && currentDraft && (
                <button
                  className="af-btn af-btn-danger"
                  onClick={() => void handleDiscard()}
                  disabled={pending}
                >
                  <Trash2 size={14} /> Discard
                </button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                className="af-btn"
                onClick={requestClose}
                disabled={pending}
              >
                Close
              </button>
              {canEdit && (
                <>
                  <button
                    className="af-btn"
                    onClick={() => void handleSave()}
                    disabled={pending || (isNew && !form.templateName.trim())}
                  >
                    {createDraft.isPending || updateDraft.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Save size={14} />
                    )}{" "}
                    Save draft
                  </button>
                  {!isNew && currentDraft && (
                    <button
                      className="af-btn af-btn-primary"
                      onClick={() => void handlePublish()}
                      disabled={pending || dirty}
                      title={
                        dirty ? "Save the draft before publishing" : undefined
                      }
                    >
                      {publishDraft.isPending ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Upload size={14} />
                      )}{" "}
                      Publish
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
