import { chromium } from '@playwright/test';
import fs from 'node:fs';

const OUT = process.argv[2];
const BASE = 'http://127.0.0.1:3005';
const ENV = '/Users/ananiyataye/Work/aai-labs/agent-farm/agent-farm-af-budgets/.env';

function env(name) {
  const line = fs.readFileSync(ENV, 'utf8').split('\n').find((l) => l.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).trim() : '';
}
const [email, password] = env('PLATFORM_ADMIN_CREDENTIALS').split(':');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

await page.goto(`${BASE}/login`);
await page.locator('#email').fill(email);
await page.locator('input[type="password"]').fill(password);
await page.getByRole('button', { name: /sign in|log ?in/i }).click();
await page.waitForURL(/dashboard\/[0-9a-f-]{36}/, { timeout: 30000 });
const orgId = page.url().split('/dashboard/')[1].split('/')[0];

// Org-facing: the warning banner on Costs
await page.goto(`${BASE}/dashboard/${orgId}/costs`);
await page.waitForTimeout(3000);
await page.screenshot({ path: `${OUT}/live-02-org-costs-warning.png` });

// Platform: the organizations list
await page.goto(`${BASE}/dashboard/platform/organizations`);
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/live-03-platform-orgs.png` });

// Platform: an enrolled org with a limit
await page.goto(`${BASE}/dashboard/platform/organizations/${orgId}`);
await page.waitForTimeout(4000);
await page.screenshot({ path: `${OUT}/live-04-platform-detail-enrolled.png` });

// Platform: the org that has never been enrolled
const other = process.argv[3];
if (other) {
  await page.goto(`${BASE}/dashboard/platform/organizations/${other}`);
  await page.waitForTimeout(5000);
  await page.screenshot({ path: `${OUT}/live-05-platform-detail-gated.png` });
}

await browser.close();
console.log('captured');
