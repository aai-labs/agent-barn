import { toast } from "sonner";

export function toastError(err: unknown, fallback = "Something went wrong.") {
  toast.error(err instanceof Error ? err.message : fallback);
}
