"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Plus } from "lucide-react";

import {
  type SkillCreatePayload,
  type SkillFilePayload,
  useCreateSkill,
} from "../hooks/use-skill-mutations";
import { skillDetailHref, skillsListHref, type SkillScopeRef } from "../scope";
import { DEFAULT_ENTRY_PATH, NEW_SKILL_TEMPLATE } from "../utils";
import { SkillFileBrowser } from "./skill-file-browser";
import { SkillMetadataFields } from "./skill-metadata-fields";

/** Creating a skill is just editing a draft that doesn't have a lineage yet, so
 * this reuses the same file browser and metadata fields as the detail page's
 * draft editor — "Create skill" is the one-step equivalent of publish. */
export function SkillNewPage({ scope }: { scope: SkillScopeRef }) {
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : null;
  const skillsHref = skillsListHref(scope, orgId);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);
  const [files, setFiles] = useState<SkillFilePayload[]>([
    { path: DEFAULT_ENTRY_PATH, content: NEW_SKILL_TEMPLATE },
  ]);
  const [fileError, setFileError] = useState<string | null>(null);

  const createSkill = useCreateSkill(scope);

  function toggleProvider(value: string) {
    setSelectedProviders((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value],
    );
  }

  async function handleCreate() {
    setFileError(null);
    if (!files.some((f) => f.path === DEFAULT_ENTRY_PATH)) {
      setFileError(`A skill must include its entry point, ${DEFAULT_ENTRY_PATH}.`);
      return;
    }
    try {
      const payload: SkillCreatePayload = {
        name: name.trim(),
        description: description.trim() || undefined,
        files,
        requiredProviders: selectedProviders,
      };
      const created = await createSkill.mutateAsync(payload);
      router.push(skillDetailHref(scope, orgId, created.id));
    } catch {
      // error displayed via createSkill.error
    }
  }

  return (
    <div className="af-page">
      <Link
        href={skillsHref}
        className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
        style={{ color: "var(--ink-3)" }}
      >
        <ArrowLeft size={14} /> {scope.kind === "agent" ? "Agent skills" : "Skills"}
      </Link>

      <div className="mb-8">
        <h1 className="text-[1.75rem] font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
          New skill
        </h1>
      </div>

      <div className="af-card overflow-hidden">
        <div className="border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
          <p className="text-[13px] leading-[1.5] m-0" style={{ color: "var(--ink-3)" }}>
            Creating a skill publishes it as version 1 immediately — from there, further
            changes go through the same draft-and-publish flow as any other skill.
          </p>
        </div>

        <div className="px-6 py-6 flex flex-col gap-6">
          {createSkill.error && (
            <div
              className="rounded-xl px-4 py-3"
              style={{
                background: "var(--err-soft)",
                border: "1px solid color-mix(in srgb, var(--err) 30%, transparent)",
              }}
            >
              <div className="font-medium text-[13px]" style={{ color: "var(--err)" }}>
                Could not create skill
              </div>
              <div className="text-[12.5px] mt-0.5" style={{ color: "var(--err)" }}>
                {createSkill.error.message}
              </div>
            </div>
          )}

          <SkillMetadataFields
            name={name}
            onNameChange={setName}
            namePlaceholder="e.g. my-tool"
            nameRequired
            description={description}
            onDescriptionChange={setDescription}
            showDescriptionHint
            selectedProviders={selectedProviders}
            onToggleProvider={toggleProvider}
          />

          <section className="flex flex-col gap-3">
            <h3 className="text-[14px] font-semibold m-0" style={{ color: "var(--ink)" }}>
              Files <span style={{ color: "var(--err)" }}>*</span>
            </h3>
            <SkillFileBrowser
              files={files}
              entryPath={DEFAULT_ENTRY_PATH}
              onFilesChange={(next) => {
                setFiles(next);
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
          <div className="flex items-center justify-end gap-2">
            <Link href={skillsHref} className="af-btn">
              Cancel
            </Link>
            <button
              className="af-btn af-btn-primary"
              disabled={createSkill.isPending || !name.trim()}
              onClick={() => void handleCreate()}
            >
              {createSkill.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create skill
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
