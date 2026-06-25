import { z } from "zod";

export const SlackConfigTokenReadSchema = z.object({
  hasToken: z.boolean(),
  tokenPreview: z.string().nullable(),
});

export type SlackConfigTokenRead = z.infer<typeof SlackConfigTokenReadSchema>;

export const CreateSlackAppResponseSchema = z.object({
  appId: z.string(),
  botTokenUrl: z.string(),
  appTokenUrl: z.string(),
});

export type CreateSlackAppResponse = z.infer<
  typeof CreateSlackAppResponseSchema
>;
