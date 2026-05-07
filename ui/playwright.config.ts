import { defineConfig, devices } from "@playwright/test";

const PORT = 3003;
const baseURL = `http://127.0.0.1:${PORT}`;
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: true,
  retries: isCI ? 2 : 0,
  workers: isCI ? 2 : 4,
  timeout: 90 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
  reporter: "list",
  use: {
    baseURL,
    actionTimeout: 15 * 1000,
    navigationTimeout: 30 * 1000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
  webServer: {
    command: `pnpm exec next dev -p ${PORT}`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120 * 1000,
    env: {
      NODE_ENV: "test",
      NEXT_PUBLIC_E2E: "true",
      NEXT_PUBLIC_BACKEND_URL: "http://127.0.0.1:8000",
    },
  },
});
