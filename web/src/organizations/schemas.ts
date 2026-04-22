import { z } from "zod";

export const OrganizationSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
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

export const PaginatedOrganizationsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(OrganizationSchema),
});

export type Organization = z.infer<typeof OrganizationSchema>;
export type OrganizationCreate = z.infer<typeof OrganizationCreateSchema>;
export type PaginatedOrganizations = z.infer<typeof PaginatedOrganizationsSchema>;
