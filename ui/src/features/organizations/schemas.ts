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
  // Platform-administered spend ceiling. Every organization has one; 0 is a real
  // zero allowance, so never coalesce it away.
  llmBudgetUsd: z.number().nullable().optional(),
  llmBudgetDuration: z.string().nullable().optional(),
  // The organization's own limit beneath the ceiling. Null follows the ceiling.
  llmOwnBudgetUsd: z.number().nullable().optional(),
});

export const OrganizationLlmBudgetSchema = z.object({
  state: z.enum(["ok", "warning", "exhausted", "unknown"]),
  // The limit in force: the organization's own, else the ceiling.
  limitUsd: z.number(),
  ceilingUsd: z.number(),
  ownLimitUsd: z.number().nullable().optional(),
  window: z.string(),
  // Null means not yet observed. Never coalesce it to 0.
  spendUsd: z.number().nullable().optional(),
  renewsAt: z.string().nullable().optional(),
  canManage: z.boolean(),
});

export const AgentLlmCoverageSchema = z.object({
  agentId: z.string().uuid(),
  agentName: z.string(),
  status: z.enum(["enrolled", "unenrolled", "other_team", "unknown_key", "unreadable"]),
});

export const OrganizationLlmCoverageSchema = z.object({
  totalAgents: z.number().int().min(0),
  enrolledAgents: z.number().int().min(0),
  uncovered: z.array(AgentLlmCoverageSchema),
  newlyEnrolled: z.number().int().min(0),
  // Null means the proxy could not be read. Never coalesce it to 0 — "we don't
  // know" and "nothing spent" are different answers.
  spendUsd: z.number().nullable().optional(),
  renewsAt: z.string().nullable().optional(),
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
export type AgentLlmCoverage = z.infer<typeof AgentLlmCoverageSchema>;
export type OrganizationLlmCoverage = z.infer<typeof OrganizationLlmCoverageSchema>;
export type OrganizationLlmBudget = z.infer<typeof OrganizationLlmBudgetSchema>;
