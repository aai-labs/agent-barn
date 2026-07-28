import { z } from "zod";

export const OrganizationSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  ownerEmail: z.string().nullable().optional(),
  ownerName: z.string().nullable().optional(),
});

export const OrganizationCreateSchema = z.object({
  name: z.string().min(3, { message: "Name must be at least 3 characters" }),
  description: z.string().optional(),
});

export const CreateOrganizationFormSchema = z.object({
  name: z.string().min(3, { message: "Name must be at least 3 characters" }),
  description: z.string().optional(),
  ownerEmail: z.string().email({ message: "Invalid email address" }),
  ownerName: z.string().optional(),
});

export const OrganizationCreateResultSchema = z.object({
  organization: OrganizationSchema,
  inviteLink: z.string().nullable(),
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

export const PaginatedOrganizationsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(OrganizationSchema),
});

export type Organization = z.infer<typeof OrganizationSchema>;
export type OrganizationCreate = z.infer<typeof OrganizationCreateSchema>;
export type CreateOrganizationFormData = z.infer<typeof CreateOrganizationFormSchema>;
export type OrganizationCreateResult = z.infer<typeof OrganizationCreateResultSchema>;
export type PaginatedOrganizations = z.infer<typeof PaginatedOrganizationsSchema>;
export type OrganizationRole = z.infer<typeof OrganizationRoleSchema>;
export type OrganizationMember = z.infer<typeof OrganizationMemberSchema>;
export type MemberInviteResult = z.infer<typeof MemberInviteResultSchema>;
export type InviteLinkResult = z.infer<typeof InviteLinkResultSchema>;
export type AddMemberFormData = z.infer<typeof AddMemberFormSchema>;
