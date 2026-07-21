import { z } from "zod";

export const SharedCredentialReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid(),
  provider: z.string(),
  name: z.string(),
  createdBy: z.string().uuid().nullable(),
  agentCount: z.number().int().min(0),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const PaginatedSharedCredentialsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(SharedCredentialReadSchema),
});

export const SharedCredentialBriefSchema = z.object({
  id: z.string().uuid(),
  provider: z.string(),
  name: z.string(),
});

export type SharedCredentialRead = z.infer<typeof SharedCredentialReadSchema>;
export type PaginatedSharedCredentials = z.infer<typeof PaginatedSharedCredentialsSchema>;
export type SharedCredentialBrief = z.infer<typeof SharedCredentialBriefSchema>;
