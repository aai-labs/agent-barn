import { createQueryKeyStructure } from "@/shared/query-keys";

// Keyed by Organization id, so switching Organization never shows the previous one's connection.
export const oneDriveSyncKey = createQueryKeyStructure("onedrive-sync");
