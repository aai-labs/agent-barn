import { PlatformAdminOnly } from "@/auth/components/platform-admin-only";
import { PlatformSkillsPage } from "@/features/skills/components/platform-skills-page";

export default function PlatformSkillsRoute() {
  return (
    <PlatformAdminOnly>
      <PlatformSkillsPage />
    </PlatformAdminOnly>
  );
}
