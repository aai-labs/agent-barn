"use client";

import { useState } from "react";

import { XIcon } from "@/components/icons";

import type { SkillFilePayload } from "../hooks/use-skill-mutations";

interface SkillFilesEditorProps {
  files: SkillFilePayload[];
  onChange: (files: SkillFilePayload[]) => void;
  readOnly?: boolean;
  entryPath: string;
}

/**
 * Flat path + content editor for a skill's files.
 *
 * Paths are relative to the skill root, and directories are implied by the path
 * ("helpers/notes.md") rather than created separately — the same way they are stored.
 */
export function SkillFilesEditor({
  files,
  onChange,
  readOnly = false,
  entryPath,
}: SkillFilesEditorProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [newPath, setNewPath] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const active = files[activeIndex] ?? files[0] ?? null;

  function updateActive(content: string) {
    onChange(files.map((f, i) => (i === activeIndex ? { ...f, content } : f)));
  }

  function handleAddFile() {
    const path = newPath.trim();
    if (!path) return;
    if (files.some((f) => f.path.toLowerCase() === path.toLowerCase())) {
      setAddError("A file with that path already exists.");
      return;
    }
    onChange([...files, { path, content: "" }]);
    setActiveIndex(files.length);
    setNewPath("");
    setAddError(null);
  }

  function handleRemove(index: number) {
    const next = files.filter((_, i) => i !== index);
    onChange(next);
    setActiveIndex((current) => (current >= next.length ? Math.max(0, next.length - 1) : current));
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        {files.map((file, index) => {
          const isEntry = file.path === entryPath;
          const isActive = index === activeIndex;
          return (
            <div
              key={`${file.path}-${index}`}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5"
              style={{
                background: isActive ? "var(--bg-soft)" : "transparent",
                border: `1px solid ${isActive ? "var(--line)" : "transparent"}`,
              }}
            >
              <button
                type="button"
                className="flex-1 text-left text-[13px] font-mono truncate"
                style={{ color: "var(--ink)" }}
                onClick={() => setActiveIndex(index)}
              >
                {file.path}
              </button>
              {isEntry && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
                  style={{ background: "var(--bg)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                >
                  entry
                </span>
              )}
              {/* The entry point is what the agent is pointed at, so it cannot be removed. */}
              {!readOnly && !isEntry && (
                <button
                  type="button"
                  className="af-btn af-btn-ghost af-btn-icon af-btn-sm"
                  aria-label={`Remove ${file.path}`}
                  onClick={() => handleRemove(index)}
                >
                  <XIcon />
                </button>
              )}
            </div>
          );
        })}
      </div>

      {!readOnly && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <input
              className="af-input text-[0.8125rem] font-mono flex-1"
              value={newPath}
              placeholder="helpers/notes.md"
              onChange={(e) => {
                setNewPath(e.target.value);
                setAddError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAddFile();
                }
              }}
            />
            <button type="button" className="af-btn af-btn-sm" onClick={handleAddFile}>
              Add file
            </button>
          </div>
          {addError && (
            <span className="text-xs" style={{ color: "var(--err)" }}>
              {addError}
            </span>
          )}
        </div>
      )}

      {active && (
        <textarea
          className="af-input font-mono text-[0.8125rem]"
          style={{ minHeight: "18rem", resize: "vertical" }}
          value={active.content}
          readOnly={readOnly}
          spellCheck={false}
          aria-label={`Content of ${active.path}`}
          onChange={(e) => updateActive(e.target.value)}
        />
      )}
    </div>
  );
}
