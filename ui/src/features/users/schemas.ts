import { z } from "zod";

export const UserReadSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  fullName: z.string().nullable().optional(),
  email: z.string().email(),
  isPlatformAdmin: z.boolean(),
  emailVerifiedAt: z.string().nullable().optional(),
});

export const PaginatedUsersSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(UserReadSchema),
});

export const CreateUserSchema = z.object({
  email: z.string().email({ message: "Invalid email address" }),
  password: z
    .string()
    .min(8, { message: "Password must be at least 8 characters" })
    .regex(/[A-Z]/, {
      message: "Password must include at least one uppercase letter",
    })
    .regex(/[a-z]/, {
      message: "Password must include at least one lowercase letter",
    })
    .regex(/[0-9]/, {
      message: "Password must include at least one number",
    }),
  fullName: z.string().optional(),
  organizationId: z.string().uuid({ message: "Select an organization" }),
  role: z.enum(["MEMBER", "ADMIN"]),
});

export type UserRead = z.infer<typeof UserReadSchema>;
export type PaginatedUsers = z.infer<typeof PaginatedUsersSchema>;
export type CreateUserData = z.infer<typeof CreateUserSchema>;
