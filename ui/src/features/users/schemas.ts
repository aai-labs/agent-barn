import { z } from "zod";

import { OrganizationRoleSchema, OrganizationSchema } from "@/features/organizations/schemas";

export const UserOrganizationMembershipSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  userId: z.string().uuid(),
  organizationId: z.string().uuid(),
  role: OrganizationRoleSchema,
  organization: OrganizationSchema,
});

export const UserReadSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  fullName: z.string().nullable().optional(),
  email: z.string().email(),
  isPlatformAdmin: z.boolean(),
  emailVerifiedAt: z.string().nullable().optional(),
  // Only populated by the single-user detail endpoint — the list endpoint omits it.
  organizationUsers: z.array(UserOrganizationMembershipSchema).nullable().optional(),
});

export const PaginatedUsersSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(UserReadSchema),
});

export const PlatformUserCreateFormSchema = z.object({
  email: z.string().email({ message: "Enter a valid email address" }),
  fullName: z.string().trim().max(200).optional(),
  organizationName: z
    .string()
    .trim()
    .refine((value) => value.length === 0 || value.length >= 3, {
      message: "Organization name must be at least 3 characters",
    })
    .refine((value) => value.length <= 255, {
      message: "Organization name must be at most 255 characters",
    }),
});

export const PlatformUserCreateResultSchema = z.object({
  user: UserReadSchema,
  organization: OrganizationSchema,
  inviteLink: z.string().url(),
});

export const PlatformUserInviteResultSchema = z.object({
  inviteLink: z.string().url(),
});

export type UserRead = z.infer<typeof UserReadSchema>;
export type UserOrganizationMembership = z.infer<
  typeof UserOrganizationMembershipSchema
>;
export type PaginatedUsers = z.infer<typeof PaginatedUsersSchema>;
export type PlatformUserCreateForm = z.infer<
  typeof PlatformUserCreateFormSchema
>;
export type PlatformUserCreateResult = z.infer<
  typeof PlatformUserCreateResultSchema
>;
