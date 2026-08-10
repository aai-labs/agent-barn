import { z } from "zod";

export const OrganizationSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  ownerEmail: z.string().nullable().optional(),
  ownerName: z.string().nullable().optional(),
  // Tolerate lightweight org views (e.g. the account/user-context memberships)
  // that don't carry the allowlist; the full org endpoint always sends it.
  allowedModels: z.array(z.string()).default([]),
});

export const OrganizationCreateSchema = z.object({
  name: z.string().min(3, { message: "Name must be at least 3 characters" }),
  description: z.string().optional(),
});

export const CreateOrganizationFormSchema = z.object({
  name: z.string().min(3, { message: "Name must be at least 3 characters" }),
  description: z.string().optional(),
});

export const OrganizationRoleSchema = z.enum(["ADMIN", "MEMBER", "OWNER"]);

export const OrganizationMemberSchema = z.object({
  userId: z.string().uuid(),
  email: z.string(),
  fullName: z.string().nullable().optional(),
  role: OrganizationRoleSchema,
  isPending: z.boolean(),
});

export const OrganizationMembersSchema = z.array(OrganizationMemberSchema);

export const MemberInviteResultSchema = z.object({
  member: OrganizationMemberSchema,
  inviteLink: z.string().nullable(),
});

export const InviteLinkResultSchema = z.object({
  inviteLink: z.string(),
});

export const AddMemberFormSchema = z.object({
  email: z.string().email({ message: "Invalid email address" }),
  fullName: z.string().optional(),
  role: z.enum(["ADMIN", "MEMBER"]),
});

// Dedicated Platform View read models — kept separate from OrganizationSchema /
// OrganizationMemberSchema above since the platform detail endpoints return a
// different (Creator-identity-including) shape than the member-facing routes.
export const PlatformOrganizationSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  ownerUserId: z.string().uuid().nullable().optional(),
  ownerEmail: z.string().nullable().optional(),
  ownerName: z.string().nullable().optional(),
  creatorUserId: z.string().uuid().nullable().optional(),
  creatorEmail: z.string().nullable().optional(),
  creatorName: z.string().nullable().optional(),
});

export const PaginatedPlatformOrganizationsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformOrganizationSchema),
});

export const PlatformOrganizationMemberSchema = z.object({
  userId: z.string().uuid(),
  email: z.string(),
  fullName: z.string().nullable().optional(),
  role: OrganizationRoleSchema,
  isPending: z.boolean(),
});

export const PaginatedPlatformOrganizationMembersSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformOrganizationMemberSchema),
});

export type PlatformOrganization = z.infer<typeof PlatformOrganizationSchema>;
export type PaginatedPlatformOrganizations = z.infer<
  typeof PaginatedPlatformOrganizationsSchema
>;
export type PlatformOrganizationMember = z.infer<
  typeof PlatformOrganizationMemberSchema
>;
export type PaginatedPlatformOrganizationMembers = z.infer<
  typeof PaginatedPlatformOrganizationMembersSchema
>;

export type Organization = z.infer<typeof OrganizationSchema>;
export type OrganizationCreate = z.infer<typeof OrganizationCreateSchema>;
export type CreateOrganizationFormData = z.infer<typeof CreateOrganizationFormSchema>;
export type OrganizationRole = z.infer<typeof OrganizationRoleSchema>;
export type OrganizationMember = z.infer<typeof OrganizationMemberSchema>;
export type MemberInviteResult = z.infer<typeof MemberInviteResultSchema>;
export type InviteLinkResult = z.infer<typeof InviteLinkResultSchema>;
export type AddMemberFormData = z.infer<typeof AddMemberFormSchema>;
