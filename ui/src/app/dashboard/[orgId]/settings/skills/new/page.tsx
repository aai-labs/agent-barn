"use client";

import { SkillNewPage } from "@/features/skills/components/skill-new-page";

export default function SkillNewRoute() {
  return <SkillNewPage scope={{ kind: "organization" }} />;
}
