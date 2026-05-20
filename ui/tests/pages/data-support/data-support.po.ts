import { Page } from "@playwright/test";

import { AgentDataSupport } from "./agent-data-support.po";
import { AuthSupport } from "./auth-support.po";
import { UserDataSupport } from "./user-data-support.po";

export class DataSupport {
  public auth: AuthSupport;
  public users: UserDataSupport;
  public agents: AgentDataSupport;

  constructor(page: Page) {
    this.auth = new AuthSupport(page);
    this.users = new UserDataSupport(page);
    this.agents = new AgentDataSupport(page);
  }
}
