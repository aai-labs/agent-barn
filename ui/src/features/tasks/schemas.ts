import { z } from "zod";

export const AgentTaskStatusSchema = z.enum(["open", "in_progress", "done", "failed"]);

export const AgentTaskSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  title: z.string(),
  description: z.string().nullable(),
  status: AgentTaskStatusSchema,
  createdAt: z.string(),
  updatedAt: z.string(),
});

/** A Task as lists show it: what it produced, and its latest Note. */
export const AgentTaskSummarySchema = AgentTaskSchema.extend({
  fileCount: z.number().int(),
  noteCount: z.number().int(),
  latestNote: z.string().nullable(),
});

export const AgentTaskNoteSchema = z.object({
  id: z.string().uuid(),
  body: z.string(),
  createdAt: z.string(),
});

export const AgentTaskFileSchema = z.object({
  id: z.string().uuid(),
  filename: z.string(),
  contentType: z.string(),
  sizeBytes: z.number().int(),
  createdAt: z.string(),
});

export const AgentTaskDetailSchema = AgentTaskSchema.extend({
  notes: z.array(AgentTaskNoteSchema),
  files: z.array(AgentTaskFileSchema),
});

export const PaginatedAgentTasksSchema = z.object({
  items: z.array(AgentTaskSummarySchema),
  page: z.number().int(),
  pageSize: z.number().int(),
  total: z.number().int(),
});

export type AgentTaskStatus = z.infer<typeof AgentTaskStatusSchema>;
export type AgentTask = z.infer<typeof AgentTaskSchema>;
export type AgentTaskSummary = z.infer<typeof AgentTaskSummarySchema>;
export type AgentTaskNote = z.infer<typeof AgentTaskNoteSchema>;
export type AgentTaskFile = z.infer<typeof AgentTaskFileSchema>;
export type AgentTaskDetail = z.infer<typeof AgentTaskDetailSchema>;
export type PaginatedAgentTasks = z.infer<typeof PaginatedAgentTasksSchema>;
