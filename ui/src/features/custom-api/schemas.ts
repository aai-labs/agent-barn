import { z } from "zod";

export const CustomApiConnectionSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  baseUrl: z.string(),
  isolated: z.boolean(),
  appliedIsolated: z.boolean().nullable(),
  pendingApply: z.boolean(),
  authType: z.enum(["none", "bearer", "api_key", "basic"]),
  authHeaderName: z.string().nullable(),
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
  slug: z.string().optional(),
  name: z.string(),
  baseUrl: z.string(),
  isolated: z.boolean(),
  auth: z.object({
    type: z.enum(["none", "bearer", "api_key", "basic"]),
    headerName: z.string().optional(),
    token: z.string().optional(),
    username: z.string().optional(),
    password: z.string().optional(),
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
