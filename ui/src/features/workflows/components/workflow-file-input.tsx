"use client";

import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Attachment } from "@/components/ui/attachment";
import {
  ArtifactCard,
  FileSummary,
} from "@/features/artifacts/components/artifact-card";
import {
  useArtifacts,
  useArtifactDownload,
  useArtifactUpload,
} from "@/features/artifacts/hooks/use-artifacts";
import type { Artifact } from "@/features/artifacts/schemas";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import type { WorkflowInputValue } from "../run-schemas";

export function WorkflowFileInput({
  id,
  agentId,
  label,
  value,
  onChange,
  disabled,
  onUploadingChange,
}: {
  id: string;
  agentId: string;
  label: string;
  value?: WorkflowInputValue;
  onChange: (value: WorkflowInputValue) => void;
  disabled: boolean;
  onUploadingChange: (busy: boolean) => void;
}) {
  const { files } = useArtifacts(agentId);
  const upload = useArtifactUpload(agentId);
  const download = useArtifactDownload(agentId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [lastUploaded, setLastUploaded] = useState<Artifact | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const rows = files.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedId = typeof value === "object" ? value.artifactId : "";
  const selectedFile =
    rows.find((file) => file.id === selectedId) ??
    (lastUploaded?.id === selectedId ? lastUploaded : undefined);
  const busy = disabled || upload.isPending;

  if (files.error)
    return (
      <p role="alert" className="text-sm">
        Existing artifacts are unavailable.{" "}
        <button
          type="button"
          className="underline"
          onClick={() => void files.refetch()}
        >
          Retry
        </button>
      </p>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Select
          disabled={busy || files.isPending}
          value={selectedId}
          onValueChange={(id) => {
            const file = rows.find((row) => row.id === id);
            if (file)
              onChange({ artifactId: file.id, checksum: file.checksum });
          }}
        >
          <SelectTrigger
            id={id}
            aria-label={`Select file for ${label}`}
            className="h-10 w-full min-w-0 flex-1 rounded-xl data-[size=default]:h-10"
          >
            <SelectValue placeholder="Choose from Agent artifacts">
              {selectedId
                ? "Choose another artifact"
                : "Choose from Agent artifacts"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent position="popper" className="max-w-[calc(100vw-2rem)]">
            <SelectGroup>
              {rows.map((file) => (
                <SelectItem
                  key={file.id}
                  value={file.id}
                  textValue={file.filename}
                >
                  <FileSummary file={file} />
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          className="h-10 gap-2 rounded-xl px-4"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {upload.isPending ? (
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <Upload aria-hidden="true" className="size-4" />
          )}
          {upload.isPending ? "Uploading…" : "Upload file"}
        </Button>
        <input
          ref={inputRef}
          aria-label={`Upload file for ${label}`}
          type="file"
          className="hidden"
          disabled={busy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            setPendingFile(file);
            onUploadingChange(true);
            try {
              const result = await upload.mutateAsync(file);
              setLastUploaded(result);
              onChange({ artifactId: result.id, checksum: result.checksum });
            } catch {
              /* Keep the previous attachment selected after a failed upload. */
            } finally {
              setPendingFile(null);
              onUploadingChange(false);
            }
          }}
        />
      </div>
      {files.hasNextPage && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={files.isFetchingNextPage}
          onClick={() => void files.fetchNextPage()}
        >
          Load more artifacts
        </Button>
      )}
      {pendingFile && (
        <Attachment
          state="uploading"
          role="status"
          className="w-full rounded-xl"
        >
          <FileSummary
            file={{
              filename: pendingFile.name,
              size: pendingFile.size,
              contentType: pendingFile.type,
            }}
            detail="Uploading…"
          />
        </Attachment>
      )}
      {selectedFile && (
        <ArtifactCard
          file={selectedFile}
          detail="Selected input"
          onRemove={() => onChange("")}
          onDownload={() => download.mutate(selectedFile.id)}
          disabled={busy || download.isPending}
          downloading={download.isPending}
          error={
            download.variables === selectedFile.id ? download.error : undefined
          }
        />
      )}
      {upload.error && (
        <p role="alert" className="text-sm text-[var(--err)]">
          {
            getErrorDisplay(upload.error, {
              title: "Upload failed",
              description: "Upload failed. Check storage and try again.",
            }).description
          }
        </p>
      )}
      <p className="text-xs leading-relaxed text-[var(--ink-3)]">
        Choose an existing artifact or upload a file up to 100 MiB. Uploads are
        saved to this Agent; starting the run pins the selected file.
      </p>
    </div>
  );
}
