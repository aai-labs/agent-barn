import { z } from "zod";

export const ApiKeyReadSchema = z.object({
  id: z.string(),
  name: z.string(),
  tokenPrefix: z.string(),
  accessMode: z.enum(["READ_ONLY", "FULL"]),
  createdAt: z.string(),
  expiresAt: z.string().nullable(),
  revokedAt: z.string().nullable(),
  lastUsedAt: z.string().nullable(),
  status: z.enum(["ACTIVE", "REVOKED", "EXPIRED", "INVALIDATED"]),
});

export const ApiKeyListSchema = z.array(ApiKeyReadSchema);
export const ApiKeyCreatedSchema = z.object({ apiKey: ApiKeyReadSchema, token: z.string() });
export type ApiKeyRead = z.infer<typeof ApiKeyReadSchema>;
export type ApiKeyCreated = z.infer<typeof ApiKeyCreatedSchema>;
