import { z } from "zod";

export const OrganizationSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable().optional(),
  isDefault: z.boolean(),
  ownerEmail: z.string().nullable().optional(),
  ownerName: z.string().nullable().optional(),
});

export const OrganizationCreateSchema = z.object({
  name: z.string().min(3, { message: "Name must be at least 3 characters" }),
  description: z.string().optional(),
});

export type Organization = z.infer<typeof OrganizationSchema>;
export type OrganizationCreate = z.infer<typeof OrganizationCreateSchema>;
