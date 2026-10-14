import { z } from "zod";

export const OneDriveSyncStatusSchema = z.enum(["pending", "active", "disconnected"]);

export const OneDriveSyncConnectionSchema = z.object({
  // False when the server has no OneDrive sync app configured.
  available: z.boolean(),
  // Null when the Organization is not connected (or an unfinished sign-in expired).
  status: OneDriveSyncStatusSchema.nullable(),
  siteName: z.string().nullable(),
  siteUrl: z.string().nullable(),
  folderWebUrl: z.string().nullable(),
  connectedAt: z.string().nullable(),
});

export type OneDriveSyncConnection = z.infer<typeof OneDriveSyncConnectionSchema>;

export const OneDriveSyncSiteSchema = z.object({
  id: z.string(),
  name: z.string(),
  webUrl: z.string(),
});

export type OneDriveSyncSite = z.infer<typeof OneDriveSyncSiteSchema>;
