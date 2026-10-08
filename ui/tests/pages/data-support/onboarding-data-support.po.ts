import { Page } from "@playwright/test";

import UserContext from "../../fixtures/user-context.json";

export const TRIAL_ORG_ID = "77777777-7777-4777-8777-777777777777";
export const TRIAL_AGENT_ID = "88888888-8888-4888-8888-888888888888";
export const TRIAL_CONNECTION_ID = "99999999-9999-4999-8999-999999999999";
export const TRIAL_TOKEN_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
export const TRIAL_DEEP_LINK = "https://t.me/AgentBarnTestBot?start=abcDEF123";
export const TRIAL_FRESH_DEEP_LINK = "https://t.me/AgentBarnTestBot?start=freshXYZ789";

const CONNECTION_BASE = `**/api/v1/organizations/${TRIAL_ORG_ID}/agents/${TRIAL_AGENT_ID}/connections/${TRIAL_CONNECTION_ID}`;

/** A self-signed-up user whose only Organization is their trial. */
export const trialUserContext = {
  ...UserContext,
  full_name: "Jane Doe",
  email: "jane@example.com",
  is_platform_admin: false,
  signed_up_at: "2026-10-07T12:00:00Z",
  organization_users: [
    {
      ...UserContext.organization_users[0],
      organization_id: TRIAL_ORG_ID,
      organization: {
        ...UserContext.organization_users[0].organization,
        id: TRIAL_ORG_ID,
        name: "Jane's Organization",
        is_trial: true,
      },
    },
  ],
};

export function onboarding(overrides: Record<string, unknown> = {}) {
  return {
    required: true,
    completed_at: null,
    organization_id: TRIAL_ORG_ID,
    credit_usd: 10,
    agent_id: null,
    agent_name: null,
    agent_status: null,
    connection_id: null,
    telegram_bot_username: "AgentBarnTestBot",
    ...overrides,
  };
}

export const agentReady = {
  agent_id: TRIAL_AGENT_ID,
  agent_name: "Ava the Assistant",
  agent_status: "RUNNING",
  connection_id: TRIAL_CONNECTION_ID,
};

export function linkToken(status: "waiting" | "linked" | "expired", extra: Record<string, unknown> = {}) {
  return {
    id: TRIAL_TOKEN_ID,
    status,
    expires_at: "2026-10-07T12:10:00Z",
    telegram_username: status === "linked" ? "jane_doe" : null,
    ...extra,
  };
}

export class OnboardingDataSupport {
  constructor(private page: Page) {}

  async interceptGetOnboarding(body: unknown = onboarding()) {
    await this.page.route("**/api/v1/onboarding", (route) =>
      route.request().method() === "GET" ? route.fulfill({ json: body }) : route.fallback(),
    );
  }

  /** Each call to set up the Agent answers with the next response, the last repeating. */
  async interceptSetUpAgent(responses: unknown[] = [onboarding(agentReady)]) {
    const calls: number[] = [];
    await this.page.route("**/api/v1/onboarding/agent", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      calls.push(Date.now());
      return route.fulfill({ json: responses[Math.min(calls.length, responses.length) - 1] });
    });
    return calls;
  }

  async interceptCompleteOnboarding() {
    const calls: number[] = [];
    await this.page.route("**/api/v1/onboarding/complete", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      calls.push(Date.now());
      return route.fulfill({ status: 204, body: "" });
    });
    return calls;
  }

  async interceptLinkedAccounts(accounts: unknown[] = []) {
    let current = accounts;
    await this.page.route(`${CONNECTION_BASE}/telegram-links`, (route) => route.fulfill({ json: current }));
    return {
      set(next: unknown[]) {
        current = next;
      },
    };
  }

  /** Link creation answers with each URL in turn; status checks follow `statuses`, the last repeating. */
  async interceptLinkTokens({
    urls = [TRIAL_DEEP_LINK],
    statuses = ["waiting"] as ("waiting" | "linked" | "expired")[],
  } = {}) {
    let created = 0;
    let checks = 0;
    await this.page.route(`${CONNECTION_BASE}/telegram-link-tokens`, (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const url = urls[Math.min(created, urls.length - 1)];
      created += 1;
      checks = 0;
      return route.fulfill({ status: 201, json: linkToken("waiting", { url }) });
    });
    await this.page.route(`${CONNECTION_BASE}/telegram-link-tokens/${TRIAL_TOKEN_ID}`, (route) => {
      // A fresh link starts waiting again.
      const status = created > 1 ? "waiting" : statuses[Math.min(checks, statuses.length - 1)];
      checks += 1;
      return route.fulfill({ json: linkToken(status) });
    });
  }
}
