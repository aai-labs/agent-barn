import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { valueSettings } from "../pages/data-support/kpis-data-support.po";
import { KpisPage } from "../pages/kpis-page.po";

test.describe("KPI calculation guidance and settings modal", () => {
  let data: DataSupport;
  let kpis: KpisPage;

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    kpis = new KpisPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.kpis.interceptValue();
    await data.kpis.interceptActivity();
  });

  test("calculation hints work with the keyboard and return focus on dismissal", async () => {
    await kpis.goto();
    await expect(kpis.tile("kpi-hours-saved")).toContainText("Estimated from");
    await kpis.openCalculationWithKeyboard("Hours saved");
    await expect(kpis.calculation("Hours saved")).toContainText("÷ 60");
    await kpis.dismissCalculation();
    await expect(kpis.calculationButton("Hours saved")).toBeFocused();
  });

  for (const viewport of [{ width: 1440, height: 900 }, { width: 375, height: 812 }]) {
    test.describe(`at ${viewport.width}px`, () => {
      test.use({ viewport });

      test("explains hours, value, and value per dollar on click or tap", async () => {
        await kpis.goto();
        await expect(kpis.tile("kpi-hours-saved")).toContainText("Estimated from");

        for (const [label, formula] of [
          ["Hours saved", "Successful actions × minutes saved per outcome ÷ 60."],
          ["Value", "Hours saved × hourly rate."],
          ["Value per dollar spent", "Estimated value ÷ LLM spend."],
        ]) {
          await kpis.openCalculation(label);
          await expect(kpis.calculation(label)).toContainText(formula);
          await kpis.dismissCalculation();
          await expect(kpis.calculation(label)).toHaveCount(0);
        }
      });

      test("explains what each value-vs-spend point represents", async () => {
        await kpis.goto();
        await expect(kpis.trend()).toContainText("Estimated value and recorded LLM spend per day.");
        await kpis.openCalculation("Value vs spend");
        await expect(kpis.calculation("Value vs spend")).toContainText("value is hours saved × hourly rate");
        await expect(kpis.calculation("Value vs spend")).toContainText("Each point shows only that interval’s amounts");
      });

      test("centers a modal and keeps its footer visible while scrolling", async ({ page }) => {
        await data.kpis.interceptValueSettings();
        await kpis.goto();
        await kpis.openValueSettings();
        await expect(kpis.rateInput()).toHaveValue("60");
        await expect(kpis.settingsDialog()).toContainText("rather than measured working time");
        const bounds = await kpis.settingsDialog().boundingBox();
        expect(bounds).not.toBeNull();
        expect(Math.abs(bounds!.x + bounds!.width / 2 - viewport.width / 2)).toBeLessThan(2);
        expect(Math.abs(bounds!.y + bounds!.height / 2 - viewport.height / 2)).toBeLessThan(2);
        expect(bounds!.width).toBeLessThan(viewport.width);
        expect(bounds!.height).toBeLessThan(viewport.height);
        await kpis.minutesInput("Record deleted").scrollIntoViewIfNeeded();
        await kpis.minutesInput("Record deleted").fill("2");
        await expect(kpis.saveSettingsButton()).toBeInViewport();
        await expect(kpis.saveSettingsButton()).toBeEnabled();
        await kpis.cancelSettings();
        await expect(kpis.discardDialog()).toBeVisible();
        await kpis.confirmDiscard();
        await expect(kpis.settingsDialog()).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Value settings", exact: true })).toBeFocused();
      });
    });
  }

  test("a reconnect preserves edits and sends only the fields the user changed", async () => {
    const settings = await data.kpis.interceptValueSettings();
    const saves = await data.kpis.interceptUpdateValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();
    await expect(kpis.rateInput()).toHaveValue("60");
    await kpis.minutesInput("Pull request opened").fill("30");

    settings.respondWith({ body: valueSettings({ hourlyRate: 100 }) });
    await data.kpis.reconnectAndWaitForSettings();
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("30");
    await kpis.saveSettingsButton().click();

    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0]).toEqual({ outcome_minutes: { PULL_REQUEST_OPENED: 30 } });
  });

  test("failed background settings reads keep the draft", async () => {
    const settings = await data.kpis.interceptValueSettings();
    await kpis.goto();
    await kpis.openValueSettings();
    await expect(kpis.rateInput()).toHaveValue("60");
    await kpis.minutesInput("Pull request opened").fill("30");
    settings.respondWith({ status: 500 });
    await data.kpis.reconnectAndWaitForSettings();
    await expect(kpis.settingsDialog()).toContainText("Unable to load value settings");
    await expect(kpis.minutesInput("Pull request opened")).toHaveValue("30");
  });

  test("a failed value refetch clears stale table figures and retry recovers", async () => {
    const value = await data.kpis.interceptValue();
    await kpis.goto();
    await expect(kpis.agentCell("Aria", "value")).toHaveText("$120.00");
    value.respondWith({ status: 500 });
    await data.kpis.reconnect();

    await expect(kpis.tile("kpi-value")).toContainText("Unable to load");
    await expect(kpis.agentCell("Aria", "value")).toHaveText("—");
    await expect(kpis.agentCell("Aria", "requests")).toHaveText("400");
    value.respondWith({ status: 200 });
    await kpis.retryAgentTable();
    await expect(kpis.agentCell("Aria", "value")).toHaveText("$120.00");
  });
});
