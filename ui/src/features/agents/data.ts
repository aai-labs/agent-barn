import type { Provider } from "./types";


export const PROVIDERS: Provider[] = [
  {
    id: "p_slack",
    name: "Slack",
    host: "slack.com, *.slack.com",
    auth: "Bearer",
    status: "active",
    keys: 3,
    lastUsed: "2s ago",
  },
  {
    id: "p_github",
    name: "GitHub",
    host: "api.github.com",
    auth: "Bearer",
    status: "active",
    keys: 2,
    lastUsed: "14s ago",
  },
  {
    id: "p_atlassian",
    name: "Atlassian",
    host: "*.atlassian.net",
    auth: "Basic",
    status: "active",
    keys: 3,
    lastUsed: "1m ago",
  },
  {
    id: "p_google",
    name: "Google Workspace",
    host: "googleapis.com",
    auth: "OAuth2",
    status: "active",
    keys: 2,
    lastUsed: "9m ago",
  },
  {
    id: "p_hubspot",
    name: "HubSpot",
    host: "api.hubapi.com",
    auth: "Bearer",
    status: "active",
    keys: 1,
    lastUsed: "3m ago",
  },
  {
    id: "p_pagerduty",
    name: "PagerDuty",
    host: "api.pagerduty.com",
    auth: "Token",
    status: "inactive",
    keys: 1,
    lastUsed: "2d ago",
  },
];

