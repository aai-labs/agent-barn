import { Page } from "@playwright/test";

import { AuthSupport } from "./auth-support.po";
import { UserDataSupport } from "./user-data-support.po";

export class DataSupport {
  public auth: AuthSupport;
  public users: UserDataSupport;

  constructor(page: Page) {
    this.auth = new AuthSupport(page);
    this.users = new UserDataSupport(page);
  }
}
