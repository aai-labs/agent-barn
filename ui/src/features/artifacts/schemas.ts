import { z } from "zod";

export const ArtifactSchema = z.object({
  id: z.string(),
  filename: z.string(),
  size: z.number(),
  contentType: z.string(),
  checksum: z.string(),
  state: z.string(),
  source: z.string(),
  publishedAt: z.string().nullable(),
  workflowId: z.string().nullable(),
  runId: z.string().nullable(),
  stepId: z.string().nullable(),
  attemptId: z.string().nullable(),
});
export type Artifact = z.infer<typeof ArtifactSchema>;
export const ArtifactListSchema = z.object({
  items: z.array(ArtifactSchema),
  total: z.number(),
  page: z.number(),
  pageSize: z.number(),
});
export const ArtifactLinkSchema = z.object({
  artifact: ArtifactSchema,
  url: z.url().refine((url) => /^https?:/.test(url), "Expected an HTTP or HTTPS download URL"),
  expiresAt: z.string(),
});
export type ArtifactList = z.infer<typeof ArtifactListSchema>;
export type ArtifactLink = z.infer<typeof ArtifactLinkSchema>;

export const ArtifactStorageSchema = z.object({
  state: z.enum(["NOT_CONFIGURED", "NOT_PROVISIONED", "PROVISIONING", "READY", "FAILED"]),
});
export type ArtifactStorage = z.infer<typeof ArtifactStorageSchema>;
