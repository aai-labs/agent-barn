import {
  File, FileArchive, FileAudio, FileCode, FileImage, FileSpreadsheet,
  FileText, FileVideo, Presentation, type LucideIcon,
} from "lucide-react";

import type { Artifact } from "../schemas";

type FileKind = {
  label: string;
  icon: LucideIcon;
  tone: "ok" | "warn" | "err" | "accent";
  extensions: string[];
  mime: RegExp;
};

const FILE_KINDS: FileKind[] = [
  { label: "PDF", icon: FileText, tone: "err", extensions: ["pdf"], mime: /^application\/pdf$/ },
  { label: "Spreadsheet", icon: FileSpreadsheet, tone: "ok", extensions: ["csv", "tsv", "xls", "xlsx", "ods"], mime: /spreadsheet|excel|^text\/(csv|tab-separated-values)$/ },
  { label: "Image", icon: FileImage, tone: "accent", extensions: ["png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "heic"], mime: /^image\// },
  { label: "Archive", icon: FileArchive, tone: "warn", extensions: ["zip", "tar", "gz", "bz2", "xz", "7z", "rar"], mime: /zip|compressed|x-tar|x-rar/ },
  { label: "Audio", icon: FileAudio, tone: "accent", extensions: ["mp3", "wav", "ogg", "flac", "m4a"], mime: /^audio\// },
  { label: "Video", icon: FileVideo, tone: "accent", extensions: ["mp4", "mov", "webm", "mkv", "avi"], mime: /^video\// },
  { label: "Presentation", icon: Presentation, tone: "warn", extensions: ["ppt", "pptx", "odp"], mime: /presentation|powerpoint/ },
  { label: "Code", icon: FileCode, tone: "accent", extensions: ["json", "xml", "html", "css", "js", "ts", "tsx", "jsx", "py", "sh", "yaml", "yml", "sql"], mime: /json|xml|javascript|^text\/(html|css)$/ },
  { label: "Document", icon: FileText, tone: "accent", extensions: ["txt", "md", "doc", "docx", "odt", "rtf"], mime: /^text\/|word|document|rtf/ },
];

export function getFileKind(file: Pick<Artifact, "filename" | "contentType">): FileKind | undefined {
  const extension = file.filename.includes(".") ? file.filename.split(".").pop()?.toLowerCase() ?? "" : "";
  return FILE_KINDS.find(kind => kind.extensions.includes(extension))
    ?? FILE_KINDS.find(kind => kind.mime.test(file.contentType.toLowerCase()));
}

export function FileTypeIcon({ file }: { file: Pick<Artifact, "filename" | "contentType"> }) {
  const kind = getFileKind(file);
  const Icon = kind?.icon ?? File;

  return (
    <span
      role="img"
      aria-label={kind ? `${kind.label} file` : "Generic file"}
      className="flex size-11 shrink-0 items-center justify-center rounded-xl"
      style={kind
        ? { color: `var(--${kind.tone === "accent" ? "accent-color" : kind.tone})`, background: `var(--${kind.tone}-soft)` }
        : { color: "var(--ink-3)", background: "var(--bg-soft)" }}
    >
      <Icon aria-hidden="true" className="size-5" strokeWidth={1.75} />
    </span>
  );
}
