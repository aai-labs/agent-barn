import { z } from "zod";

export const CustomApiConnectionSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  baseUrl: z.string(),
  isolated: z.boolean(),
  appliedIsolated: z.boolean().nullable(),
  pendingApply: z.boolean(),
  authType: z.enum(["none", "bearer", "api_key", "basic", "oauth2_client_credentials"]),
  authHeaderName: z.string().nullable(),
  authTokenUrl: z.string().nullable().optional(),
  headers: z.array(
    z.object({
      name: z.string(),
      secret: z.boolean(),
      value: z.string().nullable(),
    }),
  ),
});
export type CustomApiConnection = z.infer<typeof CustomApiConnectionSchema>;
export const CustomApiWriteSchema = z.object({
  name: z.string(),
  baseUrl: z.string(),
  isolated: z.boolean(),
  auth: z.object({
    type: z.enum(["none", "bearer", "api_key", "basic", "oauth2_client_credentials"]),
    headerName: z.string().optional(),
    token: z.string().optional(),
    username: z.string().optional(),
    password: z.string().optional(),
    tokenUrl: z.string().optional(),
    clientId: z.string().optional(),
    clientSecret: z.string().optional(),
    scope: z.string().optional(),
  }),
  headers: z.array(
    z.object({
      name: z.string(),
      value: z.string().optional(),
      secret: z.boolean(),
    }),
  ),
});
export type CustomApiWrite = z.infer<typeof CustomApiWriteSchema>;

export const CustomApiBatchSchema = z.object({
  creates: z.array(CustomApiWriteSchema),
  updates: z.array(z.object({ id: z.string(), data: CustomApiWriteSchema })),
  deletes: z.array(z.string()),
  restart: z.boolean(),
});
export type CustomApiBatch = z.infer<typeof CustomApiBatchSchema>;
