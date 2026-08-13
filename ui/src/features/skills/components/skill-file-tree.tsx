"use client";

import { useMemo, useState } from "react";
import { ChevronRight, File, Folder } from "lucide-react";

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
}: {
  node: TreeNode;
  depth: number;
  activePath: string | null;
  entryPath: string;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  onRemove?: (path: string) => void;
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
        >
          <ChevronRight
            size={13}
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
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const isActive = node.path === activePath;
  const isEntry = node.path === entryPath;
  return (
    <div
      className="flex items-center gap-1.5 rounded-lg py-1.5"
      style={{
        paddingLeft: indent + 17,
        paddingRight: 8,
        background: isActive ? "var(--bg-soft)" : "transparent",
      }}
    >
      <button
        type="button"
        className="flex-1 flex items-center gap-1.5 text-left min-w-0"
        onClick={() => onSelect(node.path)}
      >
        <File size={13} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <span
          className="text-[12.5px] font-mono truncate"
          style={{ color: isActive ? "var(--ink)" : "var(--ink-3)" }}
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
      {onRemove && !isEntry && (
        <button
          type="button"
          className="af-btn af-btn-ghost af-btn-icon af-btn-sm flex-shrink-0"
          aria-label={`Remove ${node.path}`}
          onClick={() => onRemove(node.path)}
        >
          <XIcon />
        </button>
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
}

/** Folds a skill's flat file-path list into a collapsible folder tree. */
export function SkillFileTree({ files, activePath, entryPath, onSelect, onRemove }: SkillFileTreeProps) {
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
        />
      ))}
    </div>
  );
}
