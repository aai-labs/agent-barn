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
