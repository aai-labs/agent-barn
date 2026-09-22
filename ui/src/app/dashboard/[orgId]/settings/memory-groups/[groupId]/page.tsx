"use client";

import { useParams } from "next/navigation";

import { GroupMemoryPage } from "@/features/memory-groups/components/group-memory-page";

export default function GroupMemoryRoute() {
  const params = useParams();
  const groupId = typeof params?.groupId === "string" ? params.groupId : null;

  if (!groupId) return null;
  return <GroupMemoryPage groupId={groupId} />;
}
