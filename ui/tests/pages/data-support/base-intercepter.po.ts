import { Page, Response } from "@playwright/test";

export class BaseInterceptor {
  protected page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  protected async waitForResponse(
    predicate: (response: Response) => boolean,
    options?: { timeout?: number },
  ) {
    return this.page.waitForResponse(predicate, options);
  }
}
