import { redirect } from "next/navigation";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ orgId: string; id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { orgId, id } = await params;
  const search = await searchParams;
  const query = new URLSearchParams({ tab: "workflows" });
  // A saved workflow belongs to the Organization now, so old workflow links open it there.
  if (typeof search.workflow === "string" && typeof search.workflowRun !== "string") {
    const workflows = new URLSearchParams({ workflow: search.workflow });
    for (const key of ["workflowView", "workflowVersionPage"]) {
      const value = search[key];
      if (typeof value === "string") workflows.set(key, value);
    }
    redirect(`/dashboard/${orgId}/workflows?${workflows}`);
  }
  for (const key of ["workflowRun", "workflowRunPage"]) {
    const value = search[key];
    if (typeof value === "string") query.set(key, value);
  }
  redirect(`/dashboard/${orgId}/agents/${id}?${query}`);
}
