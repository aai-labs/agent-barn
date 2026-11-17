import type { Locator, Page } from "@playwright/test";

function localDay(daysAgo: number): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysAgo);
}

/** The start of a day counted back from today, as the picker sends it. */
export function dayStartIso(daysAgo: number): string {
  return localDay(daysAgo).toISOString();
}

/** A local day as the calendar names it in `data-day`. */
function calendarDay(daysAgo: number): string {
  const day = localDay(daysAgo);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/** The days picker on the resource usage pages. */
export class UsageDatePickerPage {
  constructor(private readonly page: Page) {}

  trigger(): Locator {
    return this.page.getByRole("button", { name: "Time range" });
  }

  /** A day of the open calendar, counted back from today. */
  day(daysAgo: number): Locator {
    return this.page.locator(`[data-day="${calendarDay(daysAgo)}"]:not([data-outside]) button`);
  }

  /** The days that can be picked in the open calendar. */
  enabledDays(): Locator {
    return this.page.locator("[data-day]:not([data-outside]) button:not([disabled])");
  }

  /** Picks the last `days` days, today included, and closes the calendar. */
  async chooseLastDays(days: number) {
    await this.trigger().click();
    await this.day(days - 1).click();
    await this.day(0).click();
    await this.page.keyboard.press("Escape");
  }
}
