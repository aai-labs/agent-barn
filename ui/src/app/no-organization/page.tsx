import { redirect } from "next/navigation";

/** Old bookmarks resolve the current memberships, including the one-time backfill. */
export default function NoOrganizationPage() {
  redirect("/dashboard");
}
