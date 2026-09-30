"use client";

import { useMemo, useState } from "react";
import { ChevronRight, File, Folder, Pencil } from "lucide-react";

import { XIcon } from "@/components/icons";

interface FileEntry {
  path: string;
  content: string;
}

type TreeNode =
  | { kind: "folder"; name: string; path: string; children: TreeNode[] }
  | { kind: "file"; name: string; path: string };

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode & { kind: "folder" } = { kind: "folder", name: "", path: "", children: [] };

  for (const path of [...paths].sort()) {
    const segments = path.split("/");
    let cursor = root;
    for (let i = 0; i < segments.length; i++) {
      const isFile = i === segments.length - 1;
      const segmentPath = segments.slice(0, i + 1).join("/");
      if (isFile) {
        cursor.children.push({ kind: "file", name: segments[i], path: segmentPath });
        continue;
      }
      let next = cursor.children.find(
        (n): n is TreeNode & { kind: "folder" } => n.kind === "folder" && n.path === segmentPath,
      );
      if (!next) {
        next = { kind: "folder", name: segments[i], path: segmentPath, children: [] };
        cursor.children.push(next);
      }
      cursor = next;
    }
  }
  return root.children;
}

function TreeRow({
  node,
  depth,
  activePath,
  entryPath,
  collapsed,
  onToggle,
  onSelect,
  onRemove,
  onRename,
}: {
  node: TreeNode;
  depth: number;
  activePath: string | null;
  entryPath: string;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  onRemove?: (path: string) => void;
  onRename?: (oldPath: string, newPath: string) => void;
}) {
  const indent = 10 + depth * 16;

  if (node.kind === "folder") {
    const isOpen = !collapsed.has(node.path);
    return (
      <div>
        <button
          type="button"
          className="w-full flex items-center gap-1.5 rounded-lg py-1.5 text-left transition-colors hover:bg-[var(--bg-soft)]"
          style={{ paddingLeft: indent, paddingRight: 8 }}
          onClick={() => onToggle(node.path)}
          title={node.name}
        >
          <ChevronRight
            size={13}
            className="flex-shrink-0"
            style={{ color: "var(--ink-4)", transform: isOpen ? "rotate(90deg)" : "none", transition: "transform .12s" }}
          />
          <Folder size={13} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
          <span className="text-[12.5px] font-medium truncate" style={{ color: "var(--ink-2)" }}>
            {node.name}
          </span>
        </button>
        {isOpen && (
          <div>
            {node.children.map((child) => (
              <TreeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                activePath={activePath}
                entryPath={entryPath}
                collapsed={collapsed}
                onToggle={onToggle}
                onSelect={onSelect}
                onRemove={onRemove}
                onRename={onRename}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <FileTreeRow
      node={node}
      indent={indent}
      isActive={node.path === activePath}
      isEntry={node.path === entryPath}
      onSelect={onSelect}
      onRemove={onRemove}
      onRename={onRename}
    />
  );
}

function FileTreeRow({
  node,
  indent,
  isActive,
  isEntry,
  onSelect,
  onRemove,
  onRename,
}: {
  node: TreeNode & { kind: "file" };
  indent: number;
  isActive: boolean;
  isEntry: boolean;
  onSelect: (path: string) => void;
  onRemove?: (path: string) => void;
  onRename?: (oldPath: string, newPath: string) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(node.name);

  function commitRename() {
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === node.name) {
      setRenaming(false);
      return;
    }
    if (/\s/.test(trimmed)) {
      setRenaming(false);
      return;
    }
    if (onRename) {
      const dir = node.path.includes("/") ? node.path.slice(0, node.path.lastIndexOf("/") + 1) : "";
      onRename(node.path, dir + trimmed);
    }
    setRenaming(false);
  }

  return (
    <div
      className={`group/row flex items-center gap-1.5 rounded-lg py-1.5 transition-colors ${
        isActive ? "" : "hover:bg-[var(--bg-soft)]"
      }`}
      style={{
        paddingLeft: indent + 17,
        paddingRight: 8,
        background: isActive ? "var(--bg-soft)" : "transparent",
      }}
    >
      {renaming ? (
        <>
          <File size={13} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
          <input
            autoFocus
            className="af-input text-[12.5px] font-mono flex-1 min-w-0 py-0.5 px-1"
            value={renameValue}
            spellCheck={false}
            onChange={(e) => setRenameValue(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitRename();
              } else if (e.key === "Escape") {
                setRenameValue(node.name);
                setRenaming(false);
              }
            }}
          />
        </>
      ) : (
        <>
          <button
            type="button"
            className="flex-1 flex items-center gap-1.5 text-left min-w-0"
            onClick={() => onSelect(node.path)}
            title={node.name}
          >
            <File size={13} style={{ color: isActive ? "var(--ink-3)" : "var(--ink-4)", flexShrink: 0 }} />
            <span
              className="text-[12.5px] font-mono truncate"
              style={{ color: isActive ? "var(--ink)" : "var(--ink-3)", fontWeight: isActive ? 500 : 400 }}
            >
              {node.name}
            </span>
          </button>
          {isEntry && (
            <span
              className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
              style={{ background: "var(--bg)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
            >
              entry
            </span>
          )}
          {onRemove && (
            <div className="flex items-center gap-0.5 flex-shrink-0 opacity-0 group-hover/row:opacity-100 focus-within:opacity-100 transition-opacity">
              {onRename && !isEntry && (
                <button
                  type="button"
                  className="af-btn af-btn-ghost flex-shrink-0 justify-center"
                  style={{ width: 22, height: 22, padding: 0 }}
                  aria-label={`Rename ${node.path}`}
                  onClick={() => {
                    setRenameValue(node.name);
                    setRenaming(true);
                  }}
                >
                  <Pencil size={11} />
                </button>
              )}
              {!isEntry && (
                <button
                  type="button"
                  className="af-btn af-btn-ghost flex-shrink-0 justify-center"
                  style={{ width: 22, height: 22, padding: 0 }}
                  aria-label={`Remove ${node.path}`}
                  onClick={() => onRemove(node.path)}
                >
                  <XIcon />
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface SkillFileTreeProps {
  files: FileEntry[];
  activePath: string | null;
  entryPath: string;
  onSelect: (path: string) => void;
  onRemove?: (path: string) => void;
  onRename?: (oldPath: string, newPath: string) => void;
}

/** Folds a skill's flat file-path list into a collapsible folder tree. */
export function SkillFileTree({ files, activePath, entryPath, onSelect, onRemove, onRename }: SkillFileTreeProps) {
  const tree = useMemo(() => buildTree(files.map((f) => f.path)), [files]);
  // Track collapsed (not expanded) folders, so folders default open — including ones
  // that didn't exist yet when this component mounted — without syncing via an effect.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());

  function toggle(path: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-0.5">
      {tree.map((node) => (
        <TreeRow
          key={node.path}
          node={node}
          depth={0}
          activePath={activePath}
          entryPath={entryPath}
          collapsed={collapsed}
          onToggle={toggle}
          onSelect={onSelect}
          onRemove={onRemove}
          onRename={onRename}
        />
      ))}
    </div>
  );
}
