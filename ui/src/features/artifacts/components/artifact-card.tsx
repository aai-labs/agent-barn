"use client";

import { CircleAlert, Download, Loader2, Trash2, X } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentDescription,
  AttachmentMedia,
  AttachmentTitle,
} from "@/components/ui/attachment";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import type { Artifact } from "../schemas";
import { FileTypeIcon, getFileKind } from "./file-type-icon";

type FileDisplay = Pick<Artifact, "filename" | "size"> &
  Partial<Pick<Artifact, "contentType">>;

export function FileSummary({
  file,
  detail,
}: {
  file: FileDisplay;
  detail?: string;
}) {
  const typedFile = {
    ...file,
    contentType: file.contentType ?? "application/octet-stream",
  };
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
      <AttachmentMedia className="w-11 rounded-xl bg-transparent">
        <FileTypeIcon file={typedFile} />
      </AttachmentMedia>
      <AttachmentContent className="text-left">
        <AttachmentTitle className="whitespace-normal break-all text-sm leading-snug text-[var(--ink)]">
          {file.filename}
        </AttachmentTitle>
        <AttachmentDescription className="mt-1 whitespace-normal break-words leading-relaxed text-[var(--ink-3)]">
          {file.size.toLocaleString()} bytes ·{" "}
          {getFileKind(typedFile)?.label ?? "File"}
          {detail && ` · ${detail}`}
        </AttachmentDescription>
      </AttachmentContent>
    </div>
  );
}

export function ArtifactCard({
  file,
  detail,
  onDownload,
  onDelete,
  onRemove,
  downloading = false,
  disabled = false,
  error,
}: {
  file: FileDisplay;
  detail?: string;
  onDownload?: () => void;
  onDelete?: () => void;
  onRemove?: () => void;
  downloading?: boolean;
  disabled?: boolean;
  error?: unknown;
}) {
  return (
    <Attachment className="w-full rounded-2xl border-[var(--line)] bg-[var(--bg-elev)] p-4 hover:border-[var(--line-strong)] sm:px-5">
      <div className="flex w-full min-w-0 items-center gap-3 sm:gap-4">
        <FileSummary file={file} detail={detail} />
        <AttachmentActions className="gap-1">
          {onDownload && (
            <AttachmentAction
              type="button"
              variant="outline"
              size="default"
              className="gap-2 rounded-lg sm:px-3"
              disabled={disabled}
              onClick={onDownload}
              aria-label={`Download ${file.filename}`}
            >
              {downloading ? (
                <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <Download aria-hidden="true" className="size-4" />
              )}
              <span className="hidden sm:inline">Download</span>
            </AttachmentAction>
          )}
          {onDelete && (
            <AttachmentAction
              type="button"
              variant="ghost"
              size="icon"
              className="text-[var(--ink-3)] hover:bg-[var(--err-soft)] hover:text-[var(--err)]"
              onClick={onDelete}
              aria-label={`Delete ${file.filename}`}
              title="Delete file"
            >
              <Trash2 aria-hidden="true" className="size-4" />
            </AttachmentAction>
          )}
          {onRemove && (
            <AttachmentAction
              type="button"
              size="icon"
              disabled={disabled}
              onClick={onRemove}
              aria-label={`Remove ${file.filename}`}
            >
              <X aria-hidden="true" className="size-4" />
            </AttachmentAction>
          )}
        </AttachmentActions>
      </div>
      {Boolean(error) && (
        <Alert
          variant="destructive"
          aria-label={`Download error for ${file.filename}`}
          className="mt-3 w-full rounded-xl px-4 py-3"
          style={{
            background: "var(--err-soft)",
            borderColor: "color-mix(in srgb, var(--err) 30%, transparent)",
            color: "var(--err)",
          }}
        >
          <CircleAlert aria-hidden="true" className="size-4" />
          <AlertTitle className="text-[0.8125rem]">
            Download is unavailable
          </AlertTitle>
          <AlertDescription
            className="text-[0.8125rem] leading-relaxed"
            style={{ color: "var(--err)" }}
          >
            {getErrorDisplay(error).description}
          </AlertDescription>
        </Alert>
      )}
    </Attachment>
  );
}
