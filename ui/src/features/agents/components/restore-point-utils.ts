import type {
  Agent,
  AgentConfigurationVersion,
  RestorePoint,
  RestorePointConfigManifest,
  RestorePointSkill,
} from "../schemas";

export const RESTORE_POINT_STATUS_LABEL: Record<RestorePoint["status"], string> = {
  PENDING: "Queued",
  CAPTURING: "Capturing",
  RESTORING: "Restoring",
  READY: "Ready",
  FAILED: "Failed",
  DELETING: "Deleting",
};

/** What a system-created entry was taken for. Manual captures carry no badge. */
export const RESTORE_POINT_ORIGIN_BADGE: Record<RestorePoint["origin"], string | null> = {
  MANUAL: null,
  PRE_RESTORE: "Before restore",
  PRE_RESET: "Before reset",
  PRE_UPGRADE: "Before upgrade",
};

/**
 * Swaps Skill ids in a server message for the names the manifest recorded.
 * Validation failures name the Skill by id ("Skill <uuid> not found"), which tells
 * the reader nothing about which of their Skills is the problem.
 */
export function nameSkillsInMessage(message: string, skills: RestorePointSkill[]): string {
  return skills.reduce(
    (text, skill) => text.split(skill.skillId).join(`“${skill.name}”`),
    message,
  );
}

export function restorePointLabel(restorePoint: RestorePoint): string {
  if (restorePoint.label) return restorePoint.label;
  return restorePoint.origin === "MANUAL" ? "Untitled restore point" : "Automatic backup";
}

/** When the archive was written, falling back to when it was asked for. */
export function restorePointTime(restorePoint: RestorePoint): {
  value: string;
  isCaptureTime: boolean;
} {
  return restorePoint.capturedAt !== null
    ? { value: restorePoint.capturedAt, isCaptureTime: true }
    : { value: restorePoint.createdAt, isCaptureTime: false };
}

export function formatArchiveSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

const APPROVAL_MODE_LABEL: Record<string, string> = {
  manual: "Ask every time",
  auto: "Approve automatically",
  off: "Never ask",
};

const INHERITED_MODEL = "Organization default";

export type ConfigDiffRow = {
  key: string;
  label: string;
  recorded: string;
  current: string;
  changed: boolean;
};

// Scope matters: an Organization fork shares its platform lineage's template_key
// and restarts its own versioning, so the two can render identically.
type TemplatePin = {
  scope: "platform" | "organization" | "override" | "";
  templateKey: string;
  version: number;
};

const SCOPE_LABEL: Record<TemplatePin["scope"], string> = {
  platform: "Built-in platform",
  organization: "Organization",
  override: "Agent-owned override",
  "": "",
};

function recordedPin(manifest: RestorePointConfigManifest): TemplatePin {
  const scope = manifest.templateSelectionType;
  return {
    scope,
    templateKey: manifest.templateKey,
    version:
      scope === "override"
        ? (manifest.overrideVersion ?? manifest.templateVersion)
        : manifest.templateVersion,
  };
}

// Read from the active configuration version: the Agent DTO reports only "shared"
// or "override" and cannot name the scope.
function currentPin(active: AgentConfigurationVersion): TemplatePin {
  if (active.pinType === "override") {
    return {
      scope: "override",
      templateKey: active.sourceTemplateKey,
      version: active.version ?? active.sourceTemplateVersion,
    };
  }
  return {
    scope: active.sourceType,
    templateKey: active.sourceTemplateKey,
    version: active.sourceTemplateVersion,
  };
}

function samePin(left: TemplatePin, right: TemplatePin): boolean {
  return (
    left.scope === right.scope &&
    left.templateKey === right.templateKey &&
    left.version === right.version
  );
}

function pinDisplay(pin: TemplatePin): string {
  if (pin.scope === "") return "Not recorded";
  if (pin.scope === "override") return `${SCOPE_LABEL.override} v${pin.version}`;
  return `${SCOPE_LABEL[pin.scope]} · ${pin.templateKey} v${pin.version}`;
}

// Keyed by id: distinct lineages can share a name and version.
type SkillPins = Map<string, { name: string; version: number }>;

function sameSkills(left: SkillPins, right: SkillPins): boolean {
  if (left.size !== right.size) return false;
  for (const [id, pin] of left) {
    if (right.get(id)?.version !== pin.version) return false;
  }
  return true;
}

function skillsDisplay(pins: SkillPins): string {
  if (pins.size === 0) return "None";
  return Array.from(pins.values())
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((pin) => `${pin.name} v${pin.version}`)
    .join(", ");
}

/**
 * Every row decides `changed` from the underlying identity, never the rendered text,
 * so two different pins that happen to render the same string still read as a change.
 * A v1 manifest reports "Not recorded" for pins it never held, which is not the same
 * as recorded-and-empty.
 */
export function diffConfigManifest(
  manifest: RestorePointConfigManifest,
  agent: Agent,
  active: AgentConfigurationVersion,
): ConfigDiffRow[] {
  const recordsPins = manifest.version >= 2;
  const recordedTemplate = recordedPin(manifest);
  const currentTemplate = currentPin(active);

  const recordedSkills: SkillPins = new Map(
    manifest.skills.map((skill) => [skill.skillId, { name: skill.name, version: skill.pinnedVersion }]),
  );
  const currentSkills: SkillPins = new Map(
    agent.skills.map((skill) => [skill.id, { name: skill.name, version: skill.version }]),
  );

  return [
    {
      key: "template",
      label: "Template",
      recorded: recordsPins ? pinDisplay(recordedTemplate) : "Not recorded",
      current: pinDisplay(currentTemplate),
      changed: recordsPins ? !samePin(recordedTemplate, currentTemplate) : true,
    },
    {
      key: "model",
      label: "Model",
      recorded: manifest.model || INHERITED_MODEL,
      current: agent.model || INHERITED_MODEL,
      changed: manifest.model !== agent.model,
    },
    {
      key: "approvalMode",
      label: "Command approval",
      recorded: APPROVAL_MODE_LABEL[manifest.approvalMode] ?? manifest.approvalMode,
      current: APPROVAL_MODE_LABEL[agent.approvalMode] ?? agent.approvalMode,
      changed: manifest.approvalMode !== agent.approvalMode,
    },
    {
      key: "verboseMode",
      label: "Verbose mode",
      recorded: manifest.verboseMode ? "On" : "Off",
      current: agent.verboseMode ? "On" : "Off",
      changed: manifest.verboseMode !== agent.verboseMode,
    },
    {
      key: "skills",
      label: "Skills",
      recorded: recordsPins ? skillsDisplay(recordedSkills) : "Not recorded",
      current: skillsDisplay(currentSkills),
      changed: recordsPins ? !sameSkills(recordedSkills, currentSkills) : true,
    },
  ];
}

export function hasConfigChanges(rows: ConfigDiffRow[]): boolean {
  return rows.some((row) => row.changed);
}

/** A v1 manifest predates the template and skill pins, so it cannot be replayed. */
export function isReplayable(manifest: RestorePointConfigManifest): boolean {
  return manifest.version >= 2 && manifest.templateSelectionType !== "";
}
