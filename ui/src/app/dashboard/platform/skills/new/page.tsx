"use client";

import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { SkillNewPage } from "@/features/skills/components/skill-new-page";

export default function PlatformSkillNewRoute() {
  return (
    <PlatformAdminOnly>
      <SkillNewPage scope={{ kind: "platform" }} />
    </PlatformAdminOnly>
  );
}
