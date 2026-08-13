"use client";

import { useState } from "react";

import { SkillFileTree } from "./skill-file-tree";

interface FileEntry {
  path: string;
  content: string;
}

interface SkillFileBrowserProps {
  files: FileEntry[];
  entryPath: string;
  readOnly?: boolean;
  onFilesChange?: (files: FileEntry[]) => void;
}

/** Tree browser (left) + content viewer/editor (right) for a skill's files.
 * Read-only when onFilesChange is omitted; otherwise supports adding, removing,
 * and editing file content. */
export function SkillFileBrowser({ files, entryPath, readOnly = false, onFilesChange }: SkillFileBrowserProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [newPath, setNewPath] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  // Falls back to the first file whenever the explicit selection isn't (or is no
  // longer) among the current files, e.g. on first render or after a removal —
  // derived on every render instead of synced via an effect.
  const activePath = files.some((f) => f.path === selectedPath) ? selectedPath : (files[0]?.path ?? null);
  const active = files.find((f) => f.path === activePath) ?? null;

  function updateContent(content: string) {
    if (!onFilesChange || !active) return;
    onFilesChange(files.map((f) => (f.path === active.path ? { ...f, content } : f)));
  }

  function handleAdd() {
    if (!onFilesChange) return;
    const path = newPath.trim();
    if (!path) return;
    if (files.some((f) => f.path.toLowerCase() === path.toLowerCase())) {
      setAddError("A file with that path already exists.");
      return;
    }
    onFilesChange([...files, { path, content: "" }]);
    setSelectedPath(path);
    setNewPath("");
    setAddError(null);
  }

  function handleRemove(path: string) {
    if (!onFilesChange) return;
    onFilesChange(files.filter((f) => f.path !== path));
  }

  return (
    <div className="flex flex-col md:flex-row gap-4">
      <div className="w-full md:w-56 flex-shrink-0 flex flex-col gap-2">
        <div
          className="rounded-xl p-2 overflow-auto"
          style={{ border: "1px solid var(--line)", background: "var(--bg-elev)", maxHeight: 420 }}
        >
          <SkillFileTree
            files={files}
            activePath={activePath}
            entryPath={entryPath}
            onSelect={setSelectedPath}
            onRemove={onFilesChange ? handleRemove : undefined}
          />
        </div>
        {onFilesChange && (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <input
                className="af-input text-[0.78rem] font-mono flex-1"
                value={newPath}
                placeholder="helpers/notes.md"
                onChange={(e) => {
                  setNewPath(e.target.value);
                  setAddError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
              />
              <button type="button" className="af-btn af-btn-sm" onClick={handleAdd}>
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
      </div>

      <div className="flex-1 min-w-0">
        {active ? (
          readOnly ? (
            <pre
              className="af-input min-h-[360px] overflow-auto whitespace-pre-wrap font-mono text-[12.5px] leading-[1.65] m-0"
              aria-label={`Content of ${active.path}`}
            >
              {active.content}
            </pre>
          ) : (
            <textarea
              className="af-input font-mono text-[12.5px] leading-[1.65] resize-y min-h-[360px] w-full"
              aria-label={`Content of ${active.path}`}
              value={active.content}
              spellCheck={false}
              onChange={(e) => updateContent(e.target.value)}
            />
          )
        ) : (
          <div className="text-[13px]" style={{ color: "var(--ink-4)" }}>
            No files.
          </div>
        )}
      </div>
    </div>
  );
}
