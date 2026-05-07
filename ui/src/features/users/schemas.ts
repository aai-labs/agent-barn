import { z } from "zod";

export const UserReadSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  fullName: z.string().nullable().optional(),
  email: z.string().email(),
  isSuperuser: z.boolean(),
  emailVerifiedAt: z.string().nullable().optional(),
});

export const PaginatedUsersSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(UserReadSchema),
});

export type UserRead = z.infer<typeof UserReadSchema>;
export type PaginatedUsers = z.infer<typeof PaginatedUsersSchema>;
