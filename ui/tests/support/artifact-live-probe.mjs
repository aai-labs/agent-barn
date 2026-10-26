// Opt-in real API/Garage probe: no route interception or synthetic download response.
import { chromium, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(`${process.env.ARTIFACT_LIVE_UI}/login`);
  await page.locator('input[type="email"]').fill("admin@example.com");
  await page.locator('input[name="password"]').fill("StrongPass123");
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForURL(/dashboard/, { timeout: 60000 });
  await page.goto(`${process.env.ARTIFACT_LIVE_UI}/dashboard/${process.env.ARTIFACT_LIVE_ORG}/agents/${process.env.ARTIFACT_LIVE_AGENT}?tab=files`);
  const files = page.getByRole("region", { name: "Agent artifacts", exact: true });
  await expect(files).toContainText("hermes-live.csv", { timeout: 60000 });
  await expect(files).toContainText("openclaw-live.csv");
  for (const name of ["hermes-live.csv", "openclaw-live.csv", "hermes-live.csv"]) {
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: `Download ${name}`, exact: true }).click();
    const download = await pending;
    expect(new URL(download.url()).origin).toBe(process.env.ARTIFACT_LIVE_UI);
    expect(new URL(download.url()).pathname).toMatch(/^\/api\/v1\/agent-artifacts\//);
    expect(download.suggestedFilename()).toBe(name);
    expect(await readFile(await download.path())).toEqual(Buffer.from(process.env.ARTIFACT_LIVE_CONTENT, "base64"));
  }
  if (process.env.ARTIFACT_LIVE_SCREENSHOT) await page.screenshot({ path: process.env.ARTIFACT_LIVE_SCREENSHOT, fullPage: true });
  console.log("Real sign-in, Agent Files and three verified Garage downloads passed");
} finally {
  await browser.close();
}
