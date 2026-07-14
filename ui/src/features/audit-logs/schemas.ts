import { z } from "zod";

export const AuditLogReadSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  organizationId: z.string().uuid().nullable().optional(),
  organizationName: z.string().nullable().optional(),
  actorUserId: z.string().uuid().nullable().optional(),
  actorEmail: z.string().nullable().optional(),
  actorName: z.string().nullable().optional(),
  isSuperuserActor: z.boolean().default(false),
  action: z.string(),
  targetType: z.string().nullable().optional(),
  targetId: z.string().nullable().optional(),
  targetLabel: z.string().nullable().optional(),
  // {field: {old, new}} for allowlisted fields, {field: "[redacted]"} otherwise.
  changedFields: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const PaginatedAuditLogsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AuditLogReadSchema),
});

export const AuditActionsSchema = z.array(z.string());

export type AuditLogRead = z.infer<typeof AuditLogReadSchema>;
export type PaginatedAuditLogs = z.infer<typeof PaginatedAuditLogsSchema>;
