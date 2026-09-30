"use client";

import { useEffect, useRef, useState } from "react";
import { File } from "lucide-react";

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

const TREE_MIN = 180;
const TREE_MAX = 520;
const TREE_DEFAULT = 252;

/** Tree browser (left) + content viewer/editor (right) for a skill's files.
 * Read-only when onFilesChange is omitted; otherwise supports adding, removing,
 * renaming, and editing file content. The split between tree and editor is
 * draggable. */
export function SkillFileBrowser({ files, entryPath, readOnly = false, onFilesChange }: SkillFileBrowserProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [newPath, setNewPath] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [treeWidth, setTreeWidth] = useState(TREE_DEFAULT);
  const draggingRef = useRef(false);

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
    if (/\s/.test(path)) {
      setAddError("File paths cannot contain spaces.");
      return;
    }
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

  function handleRename(oldPath: string, newPath: string) {
    if (!onFilesChange) return;
    if (files.some((f) => f.path.toLowerCase() === newPath.toLowerCase())) {
      return;
    }
    onFilesChange(files.map((f) => (f.path === oldPath ? { ...f, path: newPath } : f)));
    setSelectedPath(newPath);
  }

  const onPointerMove = useRef<(e: PointerEvent) => void>(() => {});
  useEffect(() => {
    onPointerMove.current = (e: PointerEvent) => {
      if (!draggingRef.current) return;
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const raw = e.clientX - rect.left;
      setTreeWidth(Math.max(TREE_MIN, Math.min(TREE_MAX, raw)));
    };
  });

  const stopDraggingRef = useRef<() => void>(() => {});
  useEffect(() => {
    stopDraggingRef.current = () => {
      draggingRef.current = false;
      document.removeEventListener("pointermove", onPointerMove.current);
      document.removeEventListener("pointerup", stopDraggingRef.current);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
  });

  function startResize(e: React.PointerEvent) {
    e.preventDefault();
    draggingRef.current = true;
    document.addEventListener("pointermove", onPointerMove.current);
    document.addEventListener("pointerup", stopDraggingRef.current);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  }

  const containerRef = useRef<HTMLDivElement>(null);
  const treePanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!treePanelRef.current) return;
    const isDesktop = window.matchMedia("(min-width: 768px)").matches;
    treePanelRef.current.style.width = isDesktop ? `${treeWidth}px` : "100%";
  }, [treeWidth]);

  return (
    <div ref={containerRef} className="flex flex-col md:flex-row md:overflow-hidden">
      {/* File tree panel — draggable width on desktop, full width on mobile */}
      <div ref={treePanelRef} className="flex flex-col gap-2 flex-shrink-0 w-full md:min-w-0">
        <div
          className="rounded-xl overflow-hidden flex flex-col"
          style={{ border: "1px solid var(--line)", background: "var(--bg-elev)", maxHeight: 420 }}
        >
          <div
            className="flex items-center justify-between px-3 flex-shrink-0"
            style={{ height: 37, borderBottom: "1px solid var(--line)", background: "var(--bg-soft)" }}
          >
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>
              Files
            </span>
            <span className="text-[11px] font-mono" style={{ color: "var(--ink-4)" }}>
              {files.length}
            </span>
          </div>
          <div className="p-2 overflow-auto">
            <SkillFileTree
              files={files}
              activePath={activePath}
              entryPath={entryPath}
              onSelect={setSelectedPath}
              onRemove={onFilesChange ? handleRemove : undefined}
              onRename={onFilesChange ? handleRename : undefined}
            />
          </div>
        </div>
        {onFilesChange && (
          <div className="flex flex-col gap-1 mt-2">
            <div className="flex items-center gap-1.5">
              <input
                className="af-input text-[0.78rem] font-mono flex-1 min-w-0"
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
              <button type="button" className="af-btn af-btn-sm flex-shrink-0" onClick={handleAdd}>
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

      {/* Resizer (desktop only) */}
      <div
        className="group hidden md:flex flex-shrink-0 cursor-col-resize items-center justify-center"
        style={{ width: 10, background: "transparent" }}
        onPointerDown={startResize}
      >
        <div
          className="transition-colors group-hover:bg-[var(--ink-4)]"
          style={{ width: 2, height: 32, background: "var(--line-strong)", borderRadius: 2 }}
        />
      </div>

      {/* Editor panel */}
      <div className="flex-1 min-w-0 flex flex-col md:overflow-hidden">
        {active ? (
          <div
            className="rounded-xl overflow-hidden flex flex-col flex-1 min-h-0 transition-colors focus-within:border-[var(--ink)]"
            style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
          >
            <div
              className="flex items-center gap-2 px-3 flex-shrink-0"
              style={{ height: 37, borderBottom: "1px solid var(--line)", background: "var(--bg-soft)" }}
            >
              <File size={12} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
              <span className="text-[12px] font-mono truncate" style={{ color: "var(--ink-3)" }}>
                {active.path}
              </span>
              {active.path === entryPath && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0"
                  style={{ background: "var(--bg)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                >
                  entry
                </span>
              )}
            </div>
            {readOnly ? (
              <pre
                className="min-h-[360px] overflow-auto whitespace-pre-wrap font-mono text-[12.5px] leading-[1.65] m-0 p-3 flex-1"
                style={{ color: "var(--ink)" }}
                aria-label={`Content of ${active.path}`}
              >
                {active.content}
              </pre>
            ) : (
              <textarea
                className="font-mono text-[12.5px] leading-[1.65] resize-y min-h-[360px] w-full p-3 flex-1 outline-none"
                style={{ color: "var(--ink)", background: "transparent" }}
                aria-label={`Content of ${active.path}`}
                value={active.content}
                spellCheck={false}
                onChange={(e) => updateContent(e.target.value)}
              />
            )}
          </div>
        ) : (
          <div
            className="rounded-xl flex items-center justify-center min-h-[360px] text-[13px]"
            style={{ border: "1px dashed var(--line-strong)", color: "var(--ink-4)" }}
          >
            No files.
          </div>
        )}
      </div>
    </div>
  );
}
