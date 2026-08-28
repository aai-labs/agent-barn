"use client";

import { useParams } from "next/navigation";

import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";
import { SkillDetailPage } from "@/features/skills/components/skill-detail-page";

export default function SkillDetailRoute() {
  const params = useParams();
  const skillId = typeof params?.skillId === "string" ? params.skillId : null;
  const { canManage } = useActiveOrgRole();

  if (!skillId) return null;
  return <SkillDetailPage skillId={skillId} scope={{ kind: "organization" }} canManage={canManage} />;
}
