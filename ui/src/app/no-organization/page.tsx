import { redirect } from "next/navigation";

/** Old bookmarks enter the same organization recovery path as sign-in. */
export default function NoOrganizationPage() {
  redirect("/dashboard");
}
