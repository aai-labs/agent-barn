import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for the organization KPIs page. Assertions live in the spec. */
export class KpisPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/kpis`);
  }

  async gotoHome() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}`);
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "KPIs", exact: true });
  }

  inlineNavLinks(): Locator {
    return this.page.locator("header nav").getByRole("link");
  }

  inlineNavLink(name: string): Locator {
    return this.page.locator("header nav").getByRole("link", { name, exact: true });
  }

  async gotoWithRange(from: string, to: string) {
    const params = new URLSearchParams({ from, to });
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/kpis?${params.toString()}`);
  }

  tile(testId: string): Locator {
    return this.page.getByTestId(testId);
  }

  async retryTile(testId: string) {
    await this.tile(testId).getByRole("button", { name: "Retry" }).click();
  }

  spendLink(): Locator {
    return this.tile("kpi-spend").getByRole("link", { name: "View in Costs" });
  }

  trend(): Locator {
    return this.page.getByTestId("kpi-trend");
  }

  chartTab(name: "Value vs spend" | "Requests"): Locator {
    return this.trend().getByRole("tab", { name, exact: true });
  }

  async showChart(name: "Value vs spend" | "Requests") {
    await this.chartTab(name).click();
  }

  chartAreas(testId: string): Locator {
    return this.page.getByTestId(testId).locator(".recharts-area");
  }

  async retryTrend() {
    await this.trend().getByRole("button", { name: "Retry" }).click();
  }

  agentTable(): Locator {
    return this.page.getByTestId("kpi-agents");
  }

  agentNames(): Promise<string[]> {
    return this.agentTable().locator("tbody tr [data-agent-name]").allInnerTexts();
  }

  agentRow(name: string): Locator {
    return this.agentTable().locator("tbody tr").filter({ hasText: name });
  }

  agentCell(name: string, column: string): Locator {
    return this.agentRow(name).locator(`td[data-column="${column}"]`);
  }

  columnHeader(label: string): Locator {
    return this.agentTable().getByRole("columnheader", { name: label, exact: true });
  }

  async sortBy(label: string) {
    await this.agentTable().getByRole("button", { name: label, exact: true }).click();
  }

  async retryAgentTable() {
    await this.agentTable().getByRole("button", { name: "Retry" }).click();
  }

  footnotes(): Locator {
    return this.page.getByTestId("kpi-footnotes");
  }

  topOutcomes(): Locator {
    return this.footnotes().getByRole("listitem");
  }

  emptyState(): Locator {
    return this.page.getByTestId("kpi-empty");
  }

  tileSkeletons(): Locator {
    return this.page.getByTestId("kpi-tile-skeleton");
  }

  chartSkeleton(): Locator {
    return this.page.getByTestId("kpi-chart-skeleton");
  }

  tableSkeleton(): Locator {
    return this.page.getByTestId("kpi-table-skeleton");
  }

  async openValueSettings() {
    await this.page.getByRole("button", { name: "Value settings" }).click();
  }

  settingsSheet(): Locator {
    return this.page.getByRole("dialog", { name: "Value settings" });
  }

  rateInput(): Locator {
    return this.settingsSheet().getByLabel("Hourly rate (USD)");
  }

  outcomeRow(label: string): Locator {
    return this.settingsSheet().getByRole("group", { name: label, exact: true });
  }

  minutesInput(label: string): Locator {
    return this.outcomeRow(label).getByRole("textbox");
  }

  async resetToDefault(label: string) {
    await this.outcomeRow(label).getByRole("button", { name: /Reset to default/ }).click();
  }

  saveSettingsButton(): Locator {
    return this.settingsSheet().getByRole("button", { name: "Save", exact: true });
  }

  async closeSettingsWithX() {
    await this.settingsSheet().getByRole("button", { name: "Close", exact: true }).click();
  }

  async cancelSettings() {
    await this.settingsSheet().getByRole("button", { name: "Cancel", exact: true }).click();
  }

  async pressEscape() {
    await this.page.keyboard.press("Escape");
  }

  discardDialog(): Locator {
    return this.page.getByRole("dialog", { name: "Discard unsaved changes?" });
  }

  async confirmDiscard() {
    await this.discardDialog().getByRole("button", { name: "Discard", exact: true }).click();
  }

  async keepEditing() {
    await this.discardDialog().getByRole("button", { name: "Cancel", exact: true }).click();
  }

  async retrySettings() {
    await this.settingsSheet().getByRole("button", { name: "Retry" }).click();
  }

  windowLabel(): Locator {
    return this.page.getByTestId("kpi-window");
  }

  /** Picks two days of the month the calendar opens on. */
  async chooseDateRange() {
    await this.page.getByLabel("Date range").click();
    const days = this.page.getByRole("gridcell").filter({ hasText: /^\d+$/ });
    await days.nth(4).click();
    await days.nth(9).click();
  }

  async openNavigationDrawer() {
    await this.page.getByRole("button", { name: "Open navigation" }).click();
  }

  drawer(): Locator {
    return this.page.getByRole("dialog");
  }

  drawerLinks(): Locator {
    return this.drawer().getByRole("link");
  }

  drawerLink(name: string): Locator {
    return this.drawer().getByRole("link", { name, exact: true });
  }
}
