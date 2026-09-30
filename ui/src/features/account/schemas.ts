import { z } from "zod";

export const SlackConfigTokenReadSchema = z.object({
  hasToken: z.boolean(),
  tokenPreview: z.string().nullable(),
});

export type SlackConfigTokenRead = z.infer<typeof SlackConfigTokenReadSchema>;

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

export const CreateSlackAppResponseSchema = z.object({
  appId: z.string(),
  botTokenUrl: z.string(),
  appTokenUrl: z.string(),
});

export type CreateSlackAppResponse = z.infer<
  typeof CreateSlackAppResponseSchema
>;
