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
  url: z.url(),
  expiresAt: z.string(),
});
export type ArtifactList = z.infer<typeof ArtifactListSchema>;
export type ArtifactLink = z.infer<typeof ArtifactLinkSchema>;
