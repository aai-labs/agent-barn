"use client";

import { useParams } from "next/navigation";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { useCurrentUser } from "@/auth/providers/user-context-provider";
import { SkillDetailPage } from "@/features/skills/components/skill-detail-page";

function PlatformSkillDetail() {
  const params = useParams();
  const skillId = typeof params?.skillId === "string" ? params.skillId : null;
  const { user } = useCurrentUser();

  if (!skillId) return null;
  return <SkillDetailPage skillId={skillId} scope={{ kind: "platform" }} canManage={user.isPlatformAdmin} />;
}

export default function PlatformSkillDetailRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformSkillDetail />
    </PlatformAdminOnly>
  );
}
