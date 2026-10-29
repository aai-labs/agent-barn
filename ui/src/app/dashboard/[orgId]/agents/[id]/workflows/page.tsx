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
  for (const key of [
    "workflow",
    "workflowView",
    "workflowRun",
    "workflowRunPage",
    "workflowPage",
    "workflowVersionPage",
  ]) {
    const value = search[key];
    if (typeof value === "string") query.set(key, value);
  }
  redirect(`/dashboard/${orgId}/agents/${id}?${query}`);
}
