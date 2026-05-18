export interface Agent {
  id: string;
  name: string;
  templateVersion: number;
  status: "STOPPED" | "RUNNING" | "ERROR";
  surface: string[];
  organization_id: string;
  template_id: string;
  createdAt: string;
  updated_at: string;
  activity: string;
  activityType: string;
  tokensToday: number;
  costToday: number;
  costMonth: number;
  convsToday: number;
  toolCallsToday: number;
  uptime: string;
  cpu: number;
  mem: number;
  skills: string[];
  spark: number[];
  color: string;
  initials: string;
}

export interface AgentTemplate {
  id: string;
  slug: string;
  name: string;
  description: string;
  version: string;
  versions: string[];
  surfaces: string[];
  skills: string[];
  files: number;
  seededBy: string;
  activeAgents: number;
}

export interface Skill {
  id: string;
  name: string;
  cat: string;
  desc: string;
  installs: number;
  vetted: boolean;
  version: string;
}

export interface Provider {
  id: string;
  name: string;
  host: string;
  auth: string;
  status: "active" | "inactive";
  keys: number;
  lastUsed: string;
}

export interface ActivityEvent {
  id?: string;
  t: string;
  agent: string;
  icon: string;
  text: string;
  channel: string;
  tone: "ok" | "info" | "warn" | "err";
}

export interface ConversationMessage {
  type?: "tool";
  who?: string;
  t?: string;
  body?: string;
  name?: string;
  args?: string;
  result?: string;
}

export interface Conversation {
  id: string;
  channel: string;
  t: string;
  preview: string;
  with: string;
  live?: boolean;
  messages?: ConversationMessage[];
}
